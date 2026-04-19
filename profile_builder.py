"""Profile Builder — analyzes 30 days of behavioral data, updates user_profile table."""

import json
import logging
import re
import time
from datetime import date

from google import genai

import database as db
from agents.base import _MODEL
from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

_MIN_DATA_DAYS = 14


def build_user_profile():
    """
    Analyze behavioral data and update the user_profile table.
    Designed to run weekly (e.g., Sunday after morning routine).
    Requires at least 14 days of task history before generating entries.
    Returns a result dict with update counts, or {"skipped": True} if insufficient data.
    """
    history = db.get_recent_task_history(days=30)
    if len(history) < _MIN_DATA_DAYS:
        logger.info(
            f"profile_builder: {len(history)} days of data — need {_MIN_DATA_DAYS}. Skipping."
        )
        return {"skipped": True, "reason": f"Need {_MIN_DATA_DAYS} days of data, have {len(history)}"}

    reflections = db.get_recent_reflections(days=30)
    dow_patterns = db.get_day_of_week_patterns()
    current_profile = db.get_user_profile()

    # Detailed task-level data including completion time
    conn = db.get_connection()
    task_rows = conn.execute(
        """SELECT t.date, t.title, t.priority, t.estimated_minutes, t.completed,
                  t.completed_at, t.carried_from, g.level AS goal_type,
                  strftime('%H', t.completed_at) AS completion_hour
           FROM daily_tasks t
           LEFT JOIN goals g ON t.goal_id = g.id
           WHERE t.date >= date('now', '-30 days')
           ORDER BY t.date, t.completed_at""",
    ).fetchall()
    incomplete_rows = conn.execute(
        """SELECT t.title, g.level AS goal_type, COUNT(*) AS carry_count
           FROM daily_tasks t
           LEFT JOIN goals g ON t.goal_id = g.id
           WHERE t.date >= date('now', '-30 days')
             AND t.completed = 0 AND t.carried_from IS NOT NULL
           GROUP BY t.title
           ORDER BY carry_count DESC
           LIMIT 20""",
    ).fetchall()
    conn.close()

    mood_map = {r["date"]: r.get("mood", "") for r in reflections}

    daily_lines = []
    for h in history:
        pct = round((h.get("completed_count") or 0) / h["total"] * 100) if h["total"] else 0
        mood = mood_map.get(h["date"], "")
        daily_lines.append(
            f"  {h['date']}: {h.get('completed_count', 0)}/{h['total']} ({pct}%)"
            + (f", mood: {mood}" if mood else "")
        )

    completed_task_lines = []
    for t in task_rows:
        t = dict(t)
        if t["completed"] and t.get("completion_hour"):
            completed_task_lines.append(
                f"  {t['date']} ~{t['completion_hour']}:00 — {t['title']}"
                f" | type: {t.get('goal_type') or 'uncategorized'}"
                f" | est: {t.get('estimated_minutes') or '?'}min"
                f" | priority: {t.get('priority') or '?'}"
            )

    incomplete_lines = [
        f"  {dict(t)['title']} (type: {dict(t).get('goal_type') or '?'}) "
        f"— carried {dict(t)['carry_count']}x"
        for t in incomplete_rows
    ]

    mood_lines = [
        f"  {r['date']}: {r['mood']}"
        for r in reflections if r.get("mood")
    ]

    dow_lines = [
        f"  {p['day_name']}: {p['avg_pct']}% avg"
        for p in dow_patterns if p.get("avg_pct")
    ]

    profile_lines = [
        f"  {cat}.{key} = {data['value']}"
        f" (confidence: {data['confidence']:.2f}, data_points: {data['data_points']})"
        for cat, keys in current_profile.items()
        for key, data in keys.items()
    ]

    prompt = f"""You are analyzing a user's productivity data to build a behavioral profile. Be precise and evidence-based — only state things supported by the data.

## Raw Data (Last 30 Days)

### Daily Task Completion:
{chr(10).join(daily_lines) or "  No data."}

### Completed Task Detail (with approximate time of day):
{chr(10).join(completed_task_lines[:80]) or "  No completed task detail."}

### Incomplete / Repeatedly Carried Tasks:
{chr(10).join(incomplete_lines) or "  None."}

### Mood History:
{chr(10).join(mood_lines) or "  No mood data."}

### Day-of-Week Completion Patterns:
{chr(10).join(dow_lines) or "  No pattern data."}

### Current Profile (update, do not rebuild from scratch):
{chr(10).join(profile_lines) or "  No existing profile entries."}

## Analysis Instructions

Analyze the data and produce profile updates across these categories and keys:

work_style: peak_hours, max_tasks_per_day, preferred_task_sequence, focus_duration_minutes, context_switch_cost
goal_tendencies: avoidance_pattern, procrastination_triggers, momentum_builder, abandonment_risk_signals
scheduling: day_ratings, best_streak_day, worst_day, overload_threshold, recovery_pattern
learning: retention_strength, review_compliance, best_learning_time, chapters_before_fatigue
emotional: mood_trend, bad_day_response, praise_effectiveness, accountability_response

Rules:
1. Only include a key if at least 5 data points support it
2. If a key's value is unchanged from the current profile, keep it and increase confidence by 0.05 (max 0.95)
3. If a key's value changed, set confidence to 0.5
4. Never set confidence above 0.95 or below 0.1
5. For avoidance_pattern: use JSON like {{"career": 0.4, "learning": 0.8}} (completion rate per goal type, 0-1)
6. For day_ratings: use JSON like {{"monday": 0.78, "tuesday": 0.82, "wednesday": 0.65, "thursday": 0.71, "friday": 0.55, "saturday": 0.40, "sunday": 0.35}}
7. For procrastination_triggers and abandonment_risk_signals: use JSON arrays like ["tasks over 60 min", "career applications"]
8. Be specific: "avoids tasks over 60 minutes" beats "sometimes procrastinates"

Respond ONLY with valid JSON:
{{
  "profile_updates": [
    {{
      "category": "work_style",
      "key": "peak_hours",
      "value": "morning",
      "confidence": 0.8,
      "data_points": 22,
      "evidence": "Completed 73% of tasks before noon across 22 tracked days"
    }}
  ],
  "notable_changes": ["Description of any significant shift from previous profile"],
  "data_gaps": ["Areas without enough data for a determination"]
}}"""

    start = time.time()
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(model=_MODEL, contents=prompt)
        raw_text = response.text

        cleaned = raw_text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)

        updates_applied = 0
        for update in parsed.get("profile_updates", []):
            try:
                db.upsert_profile_entry(
                    category=update["category"],
                    key=update["key"],
                    value=str(update["value"]),
                    confidence=min(0.95, max(0.1, float(update.get("confidence", 0.5)))),
                    data_points=int(update.get("data_points", 1)),
                )
                updates_applied += 1
            except Exception as e:
                logger.warning(
                    f"profile_builder: skipped {update.get('category')}.{update.get('key')}: {e}"
                )

        duration_ms = int((time.time() - start) * 1000)
        logger.info(f"profile_builder: {updates_applied} entries updated in {duration_ms}ms")

        _log(prompt, raw_text, json.dumps(parsed), duration_ms, True, None, len(history), len(current_profile))

        return {
            "updates_applied": updates_applied,
            "notable_changes": parsed.get("notable_changes", []),
            "data_gaps": parsed.get("data_gaps", []),
        }

    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        logger.error(f"profile_builder error: {e}")
        _log(prompt, str(e), None, duration_ms, False, str(e), len(history), len(current_profile))
        raise


def _log(raw_prompt, raw_response, parsed_output, duration_ms, success, error_message,
         history_days, existing_categories):
    conn = db.get_connection()
    with conn:
        conn.execute(
            """INSERT INTO agent_logs
               (agent_name, trigger_type, input_summary, raw_prompt, raw_response,
                parsed_output, duration_ms, success, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "profile_builder", "scheduled",
                f"{history_days} days of data, {existing_categories} existing categories",
                raw_prompt, raw_response, parsed_output,
                duration_ms, int(success), error_message,
            ),
        )
    conn.close()
