import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

from google import genai

import database as db
from config import GEMINI_API_KEY

_MODEL = "gemini-3-flash-preview"


def _get_client():
    return genai.Client(api_key=GEMINI_API_KEY)


def _parse_response(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _log_response(prompt, response_text):
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"{date.today().isoformat()}.txt"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("=== PROMPT ===\n")
        f.write(prompt)
        f.write("\n\n=== RESPONSE ===\n")
        f.write(response_text)
        f.write("\n\n")


def _call_gemini(prompt):
    """Call Gemini and return response text. Raises on failure."""
    client = _get_client()
    response = client.models.generate_content(model=_MODEL, contents=prompt)
    return response.text


def _call_gemini_with_retry(prompt):
    """Call Gemini with one JSON-parse retry. Returns (data, response_text)."""
    response_text = _call_gemini(prompt)
    _log_response(prompt, response_text)
    try:
        return _parse_response(response_text), response_text
    except json.JSONDecodeError:
        retry_prompt = prompt + "\n\nIMPORTANT: Respond ONLY with valid JSON. No other text."
        response_text = _call_gemini(retry_prompt)
        _log_response(retry_prompt, response_text)
        return _parse_response(response_text), response_text


# ---------------------------------------------------------------------------
# Daily Plan Generation (Feature 1+4: smarter with context)
# ---------------------------------------------------------------------------

def _build_prompt(active_goals, history, today_tasks,
                  yesterday_reflection=None, last_weekly_review=None,
                  carried_tasks=None, dow_patterns=None,
                  pending_email_items=None):
    yearly = [g for g in active_goals if g["level"] == "yearly"]
    monthly = [g for g in active_goals if g["level"] == "monthly"]
    weekly = [g for g in active_goals if g["level"] == "weekly"]

    goal_lines = []
    for yg in yearly:
        goal_lines.append(f"- [Y] {yg['title']} (id:{yg['id']})"
                          + (f" — due {yg['deadline']}" if yg.get("deadline") else ""))
        for mg in monthly:
            if mg["parent_id"] == yg["id"]:
                goal_lines.append(f"  - [M] {mg['title']} (id:{mg['id']})"
                                  + (f" — due {mg['deadline']}" if mg.get("deadline") else ""))
                for wg in weekly:
                    if wg["parent_id"] == mg["id"]:
                        goal_lines.append(f"    - [W] {wg['title']} (id:{wg['id']})"
                                          + (f" — due {wg['deadline']}" if wg.get("deadline") else ""))
    for mg in monthly:
        if not any(mg["parent_id"] == yg["id"] for yg in yearly):
            goal_lines.append(f"  - [M] {mg['title']} (id:{mg['id']})")
            for wg in weekly:
                if wg["parent_id"] == mg["id"]:
                    goal_lines.append(f"    - [W] {wg['title']} (id:{wg['id']})")

    goals_text = "\n".join(goal_lines) if goal_lines else "No goals set yet."

    history_lines = []
    for h in history:
        titles = ", ".join(h["completed_titles"]) if h["completed_titles"] else "none"
        history_lines.append(
            f"- {h['date']}: {h['completed_count'] or 0}/{h['total']} completed — {titles}"
        )
    history_text = "\n".join(history_lines) if history_lines else "No recent history."

    existing = ""
    if today_tasks:
        existing = "\n\n## Already Planned for Today\n" + "\n".join(
            f"- {'[done]' if t['completed'] else '[todo]'} {t['title']}" for t in today_tasks
        )

    # Feature 4 context additions
    extra_context = ""

    if yesterday_reflection:
        summary = yesterday_reflection.get("ai_summary") or ""
        tomorrow_suggestions = []
        # The ai_summary may be JSON from a daily review
        try:
            parsed = json.loads(summary)
            summary_text = parsed.get("reflection", summary)
            tomorrow_suggestions = parsed.get("tomorrow_suggestions", [])
        except Exception:
            summary_text = summary

        extra_context += f"\n\n## Yesterday's Review\n{summary_text}"
        if tomorrow_suggestions:
            extra_context += "\nSuggestions for today: " + "; ".join(tomorrow_suggestions)

    if last_weekly_review and last_weekly_review.get("focus_areas"):
        focus = last_weekly_review["focus_areas"]
        if isinstance(focus, list):
            lines = []
            for item in focus:
                if isinstance(item, dict):
                    lines.append(f"- {item.get('goal_title', '')}: {item.get('suggestion', '')}")
                else:
                    lines.append(f"- {item}")
            extra_context += "\n\n## This Week's Focus Areas (from weekly review)\n" + "\n".join(lines)

    if carried_tasks:
        extra_context += "\n\n## Carried Forward from Yesterday\n" + "\n".join(
            f"- {t['title']} (carried {t.get('carry_count', 1)} time(s))"
            for t in carried_tasks
        )

    if dow_patterns:
        today_dow = date.today().strftime("%A")
        pattern_lines = [f"{p['day_name']}: ~{p['avg_pct']}% avg" for p in dow_patterns if p.get("avg_pct")]
        today_pattern = next((p for p in dow_patterns if p["day_name"] == today_dow), None)
        if pattern_lines:
            extra_context += "\n\n## Day-of-Week Pattern\n" + "\n".join(pattern_lines)
            if today_pattern:
                extra_context += f"\nToday is {today_dow} (historically ~{today_pattern['avg_pct']}% completion)."

    if pending_email_items:
        item_lines = [
            f"- [{i['priority']}] {i['title']} (from: {i.get('source_sender', '?')}, re: {i.get('source_subject', '?')})"
            for i in pending_email_items
        ]
        extra_context += (
            "\n\n## Pending Email Action Items\n"
            "The user's inbox has these unhandled action items:\n"
            + "\n".join(item_lines)
            + "\nConsider incorporating high-priority email actions into today's task list. "
            "Do NOT duplicate them — just factor them into your prioritization."
        )

    carry_rules = ""
    if carried_tasks:
        heavy = [t for t in carried_tasks if (t.get("carry_count") or 0) >= 3]
        if heavy:
            carry_rules = "\n- Tasks carried 3+ times should be flagged in daily_insight as needing to be broken down or reconsidered."
        carry_rules += "\n- Adjust task count lower if today historically has low completion."

    return f"""You are a productivity planner. Based on the user's goals and recent progress, generate a focused, realistic daily task list for today ({date.today().isoformat()}).

## User's Active Goals

{goals_text}

## Recent History (Last 7 Days)

{history_text}{existing}{extra_context}

## Rules
1. Generate 5-8 tasks maximum. Less is better than more.
2. Each task must be concrete and completable in one sitting (30min - 2hrs).
3. Prioritize tasks that are behind schedule.
4. Mix goal types — don't put all tasks under one goal.
5. Include 1 "quick win" task that takes under 15 minutes.
6. If a goal has been neglected for over a week, flag it.
7. Do NOT duplicate tasks already planned for today.
8. If yesterday's review suggested specific actions, incorporate them.
9. If weekly focus areas mention a neglected goal, include at least one task for it.{carry_rules}

## Output Format
Respond ONLY with valid JSON, no markdown, no explanation:
{{
  "tasks": [
    {{
      "title": "task title",
      "description": "1-2 sentence description of what exactly to do",
      "priority": "high|medium|low",
      "goal_id": <id of related goal or null>,
      "estimated_minutes": <number>
    }}
  ],
  "daily_insight": "One sentence of encouragement or strategic advice based on their progress patterns"
}}"""


def generate_daily_plan():
    """
    Entry point for plan generation.
    Delegates to the multi-agent orchestrator; falls back to single-prompt mode on failure.
    """
    from agents.orchestrator import Orchestrator
    try:
        orchestrator = Orchestrator()
        result = orchestrator.generate_daily_plan()
        # Persist tasks to DB (orchestrator returns task dicts, not inserted rows)
        today_str = date.today().isoformat()
        inserted = []
        for t in result.get("tasks", []):
            task = db.create_task(
                title=t.get("title", "Untitled"),
                description=t.get("description"),
                priority=t.get("priority", "medium"),
                goal_id=t.get("goal_id"),
                date_str=today_str,
                source="ai",
                estimated_minutes=t.get("estimated_minutes"),
                energy_level=t.get("energy_level"),
                suggested_slot=t.get("suggested_slot"),
                task_type=t.get("task_type", "normal"),
                spaced_review_id=t.get("spaced_review_id"),
            )
            inserted.append(task)

        all_today = db.get_tasks_for_date(today_str)
        done = sum(1 for t in all_today if t["completed"])
        db.upsert_reflection(today_str, done, len(all_today),
                             ai_summary=result.get("daily_insight"))

        result["tasks"] = inserted
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Orchestrator failed, falling back to legacy: {e}")
        return _generate_daily_plan_legacy()


def _generate_daily_plan_legacy():
    """Legacy single-prompt plan generation (fallback)."""
    active_goals = db.get_active_goals_flat()
    history = db.get_recent_task_history(days=7)
    today_tasks = db.get_tasks_for_date(date.today().isoformat())

    # Feature 4: gather context
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    yesterday_reflection = db.get_reflection_for_date(yesterday_str)
    last_weekly_review = db.get_previous_weekly_review(
        (date.today() - timedelta(days=date.today().weekday())).isoformat()
    )
    carried_tasks = [t for t in today_tasks if t.get("is_carried")]
    dow_patterns = db.get_day_of_week_patterns()

    # Phase 3: pending email action items
    pending_email_items = db.get_pending_email_action_items(date.today().isoformat())

    prompt = _build_prompt(
        active_goals, history, today_tasks,
        yesterday_reflection=yesterday_reflection,
        last_weekly_review=last_weekly_review,
        carried_tasks=carried_tasks if carried_tasks else None,
        dow_patterns=dow_patterns if dow_patterns else None,
        pending_email_items=pending_email_items if pending_email_items else None,
    )

    try:
        data, _ = _call_gemini_with_retry(prompt)
    except Exception as e:
        return {"error": f"Failed to generate plan: {str(e)}"}

    inserted = []
    today_str = date.today().isoformat()
    for t in data.get("tasks", []):
        task = db.create_task(
            title=t.get("title", "Untitled"),
            description=t.get("description"),
            priority=t.get("priority", "medium"),
            goal_id=t.get("goal_id"),
            date_str=today_str,
            source="ai",
            estimated_minutes=t.get("estimated_minutes"),
            energy_level=t.get("energy_level"),
            suggested_slot=t.get("suggested_slot"),
            task_type=t.get("task_type", "normal"),
            spaced_review_id=t.get("spaced_review_id"),
        )
        inserted.append(task)

    all_today = db.get_tasks_for_date(today_str)
    done = sum(1 for t in all_today if t["completed"])
    db.upsert_reflection(today_str, done, len(all_today), ai_summary=data.get("daily_insight"))

    return {
        "tasks": inserted,
        "daily_insight": data.get("daily_insight", ""),
    }


# ---------------------------------------------------------------------------
# Daily Review Generation (Feature 2)
# ---------------------------------------------------------------------------

def generate_daily_review(notes=None, mood=None, target_date=None):
    if target_date is None:
        target_date = date.today().isoformat()

    tasks = db.get_tasks_for_date(target_date)
    completed = [t for t in tasks if t["completed"]]
    incomplete = [t for t in tasks if not t["completed"]]

    yesterday_str = (date.fromisoformat(target_date) - timedelta(days=1)).isoformat()
    yesterday_reflection = db.get_reflection_for_date(yesterday_str)

    history = db.get_recent_task_history(days=7)

    def task_line(t):
        goal = f", linked to goal: {t['goal_title']}" if t.get("goal_title") else ""
        return f"{t['title']} (priority: {t.get('priority', 'medium')}{goal})"

    completed_lines = "\n".join(f"✓ {task_line(t)}" for t in completed) or "None"
    incomplete_lines = "\n".join(f"✗ {task_line(t)}" for t in incomplete) or "None"

    trend_lines = []
    for h in reversed(history):
        trend_lines.append(f"{h['date']}: {h['completed_count'] or 0}/{h['total']} tasks completed")
    trend_text = "\n".join(trend_lines) if trend_lines else "No history available."

    yesterday_summary = "No review yesterday"
    if yesterday_reflection and yesterday_reflection.get("ai_summary"):
        try:
            parsed = json.loads(yesterday_reflection["ai_summary"])
            yesterday_summary = parsed.get("reflection", yesterday_reflection["ai_summary"])
        except Exception:
            yesterday_summary = yesterday_reflection["ai_summary"]

    # Load active suggestions for escalation tracking
    active_suggestions = db.get_active_suggestions()
    suggestion_history_block = ""
    if active_suggestions:
        lines = ["## Suggestion History (track follow-through)"]
        for s in active_suggestions:
            pct = round(s["follow_through_rate"] * 100)
            lines.append(
                f'[id:{s["id"]}] "{s["suggestion"]}" '
                f'— given {s["times_given"]}x, followed {s["times_followed"]}x ({pct}%), '
                f'escalation level: {s["escalation_level"]}, last given: {s["last_given"]}'
            )
        suggestion_history_block = "\n".join(lines)

    escalation_rules = """
## Suggestion Tracking Rules
For each suggestion in "Suggestion History":
- Determine if the user followed it today (check completed tasks for evidence)
- If followed (follow_through_rate would be > 0.7 after this): mark resolved
- If NOT followed: it will be repeated; if given 3+ times with < 30% follow-through, escalate
- escalation_level 1 = nudge (more specific about why it matters)
- escalation_level 2 = direct question (ask what's blocking them, give response options)
- escalation_level 3 = intervention (propose concrete alternatives: break down, change deadline, pause, drop)

For NEW suggestions this review:
- Be specific and actionable ("Start tomorrow with X before checking email", not "focus on Y")
- Limit to 2 new suggestions max
- Include related_goal_id if the suggestion relates to a specific goal""" if active_suggestions else ""

    prompt = f"""You are a thoughtful productivity coach reviewing someone's day. Be honest but encouraging. Don't sugarcoat, but don't be harsh.

## Today's Results
Date: {target_date}
Tasks completed: {len(completed)}/{len(tasks)}

### Completed:
{completed_lines}

### Not completed:
{incomplete_lines}

### User's mood: {mood or "not specified"}
### User's notes: {notes or "none"}

### Yesterday's reflection (for context):
{yesterday_summary}

### 7-Day completion trend:
{trend_text}

{suggestion_history_block}
{escalation_rules}

## Instructions
1. In 2-3 sentences, reflect on how the day went. Reference specific tasks.
2. If high-priority tasks were skipped, gently note why that matters.
3. Note any patterns you see in the 7-day trend (improving? declining? inconsistent?)
4. Suggest 1-2 specific adjustments for tomorrow.
5. For each suggestion in the history, determine if it was followed today.

Respond ONLY with valid JSON:
{{
  "reflection": "Your 2-3 sentence reflection on the day",
  "patterns_noticed": "Any patterns from the 7-day trend, or null",
  "tomorrow_suggestions": ["suggestion 1", "suggestion 2"],
  "encouragement": "One short encouraging sentence",
  "suggestion_tracking": [
    {{
      "suggestion_text": "the suggestion text",
      "category": "task_prioritization|goal_focus|habit|workload|emotional",
      "is_new": true,
      "escalation_level": 0,
      "previous_id": null,
      "related_goal_id": null,
      "followed": null
    }}
  ],
  "resolved_suggestions": []
}}"""

    try:
        data, _ = _call_gemini_with_retry(prompt)
    except Exception as e:
        return {"error": f"Failed to generate review: {str(e)}"}

    # Process suggestion tracking
    _process_suggestion_tracking(data, target_date)

    # Save to daily_reflections
    done_count = len(completed)
    total_count = len(tasks)
    db.upsert_reflection(
        target_date,
        done_count,
        total_count,
        ai_summary=json.dumps(data),
        notes=notes,
        mood=mood,
    )

    return data


def _process_suggestion_tracking(review_data, review_date):
    """Persist suggestion_tracking and resolved_suggestions from the AI review."""
    for sid in review_data.get("resolved_suggestions", []):
        try:
            db.resolve_suggestion(int(sid))
        except Exception:
            pass

    for item in review_data.get("suggestion_tracking", []):
        try:
            if item.get("is_new"):
                db.create_suggestion(
                    suggestion_text=item["suggestion_text"],
                    category=item.get("category"),
                    related_goal_id=item.get("related_goal_id"),
                    given_date=review_date,
                )
            else:
                prev_id = item.get("previous_id")
                if prev_id:
                    db.update_suggestion_after_review(
                        suggestion_id=int(prev_id),
                        followed=bool(item.get("followed")),
                        new_escalation_level=item.get("escalation_level"),
                        given_date=review_date,
                    )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Weekly Review Generation (Feature 3)
# ---------------------------------------------------------------------------

def generate_weekly_review(week_start=None):
    today = date.today()
    if week_start is None:
        week_start = today - timedelta(days=today.weekday())
    elif isinstance(week_start, str):
        week_start = date.fromisoformat(week_start)

    week_end = week_start + timedelta(days=6)
    week_start_str = week_start.isoformat()
    week_end_str = week_end.isoformat()

    week_data = db.get_week_data(week_start_str, week_end_str)
    tasks = week_data["tasks"]
    reflections_by_date = {r["date"]: r for r in week_data["reflections"]}

    active_goals = db.get_active_goals_flat()
    prev_review = db.get_previous_weekly_review(week_start_str)
    recent_reviews = db.get_recent_weekly_reviews(week_start_str, limit=4)

    # Group tasks by date
    from collections import defaultdict
    tasks_by_date = defaultdict(list)
    for t in tasks:
        tasks_by_date[t["date"]].append(t)

    # Daily breakdown
    day_lines = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        ds = d.isoformat()
        day_tasks = tasks_by_date.get(ds, [])
        completed = [t for t in day_tasks if t["completed"]]
        missed = [t for t in day_tasks if not t["completed"]]
        ref = reflections_by_date.get(ds)
        mood = ref["mood"] if ref and ref.get("mood") else "not recorded"
        daily_summary = "none"
        if ref and ref.get("ai_summary"):
            try:
                parsed = json.loads(ref["ai_summary"])
                daily_summary = parsed.get("reflection", ref["ai_summary"])[:120]
            except Exception:
                daily_summary = ref["ai_summary"][:120]

        day_lines.append(
            f"{d.strftime('%A')} ({ds}): completed {len(completed)}/{len(day_tasks)} tasks\n"
            f"   - Completed: {', '.join(t['title'] for t in completed) or 'none'}\n"
            f"   - Missed: {', '.join(t['title'] for t in missed) or 'none'}\n"
            f"   - Mood: {mood}\n"
            f"   - Daily reflection: {daily_summary}"
        )

    daily_breakdown = "\n".join(day_lines)

    # Goal activity
    goal_completed_counts = defaultdict(int)
    goal_missed_counts = defaultdict(int)
    for t in tasks:
        if t.get("goal_id"):
            if t["completed"]:
                goal_completed_counts[t["goal_id"]] += 1
            else:
                goal_missed_counts[t["goal_id"]] += 1

    goal_lines = []
    goals_progressed = []
    goals_neglected = []
    for g in active_goals:
        done = goal_completed_counts.get(g["id"], 0)
        missed = goal_missed_counts.get(g["id"], 0)
        total = done + missed
        if total == 0:
            status = "no activity"
            goals_neglected.append(g["id"])
        elif done / total >= 0.7:
            status = "on-track"
            goals_progressed.append(g["id"])
        else:
            status = "falling-behind"
        goal_lines.append(
            f"Goal: {g['title']} (level: {g['level']})\n"
            f"   Tasks completed: {done}, Tasks missed: {missed}, Status: {status}"
        )
    zero_activity = [g["title"] for g in active_goals if g["id"] in goals_neglected]

    goal_activity_text = "\n".join(goal_lines) if goal_lines else "No active goals."
    zero_activity_text = "\n".join(f"- {t}" for t in zero_activity) if zero_activity else "None"

    prev_summary = "No previous review"
    if prev_review and prev_review.get("ai_review"):
        try:
            parsed = json.loads(prev_review["ai_review"])
            prev_summary = parsed.get("week_summary", prev_review["ai_review"])[:200]
        except Exception:
            prev_summary = prev_review["ai_review"][:200]

    # Build cross-week context for the narrative
    cross_week_lines = []
    for r in recent_reviews:
        try:
            parsed = json.loads(r["ai_review"])
        except Exception:
            parsed = {}
        summary = parsed.get("week_summary", "")[:200]
        trend = parsed.get("overall_trend", "unknown")
        wins = parsed.get("wins", [])
        concerns = parsed.get("concerns", [])
        cross_week_lines.append(
            f"Week of {r['week_start']} (completion: {round((r['completion_rate'] or 0) * 100)}%, trend: {trend}):\n"
            f"  Summary: {summary}\n"
            f"  Wins: {'; '.join(wins[:2]) or 'none'}\n"
            f"  Concerns: {'; '.join(concerns[:2]) or 'none'}"
        )
    cross_week_context = "\n\n".join(cross_week_lines) if cross_week_lines else "No previous reviews available."

    profile_block = db.get_profile_for_prompt()

    total_tasks = len(tasks)
    completed_tasks = sum(1 for t in tasks if t["completed"])
    completion_rate = round(completed_tasks / total_tasks, 3) if total_tasks else 0.0

    prompt = f"""You are a strategic productivity coach doing a weekly review. Be analytical and actionable.

## Week: {week_start_str} to {week_end_str}

### Daily Breakdown:
{daily_breakdown}

### Goal Activity This Week:
{goal_activity_text}

### Goals With ZERO Activity This Week:
{zero_activity_text}

### Previous Week's Summary (for trend):
{prev_summary}

### Previous Weekly Reviews (up to 4 weeks back):
{cross_week_context}

{profile_block}

## Instructions:
1. Summarize the week in 3-4 sentences. Be specific about what went well and what didn't.
2. Identify the top 2-3 goals that progressed most.
3. Flag any goals that are being consistently neglected (this week AND last week).
4. Note behavioral patterns: does the user complete more early in the week? Do they skip certain types of tasks?
5. Recommend 2-3 focus areas for next week, prioritizing neglected goals.
6. Write a narrative arc (3-5 sentences) connecting the last several weeks into a story. Reference specific data. Connect cause and effect across weeks. End with one actionable insight. If fewer than 2 previous reviews exist, write null for the narrative field. Adapt the tone to the user's accountability_response preference if known.

Respond ONLY with valid JSON:
{{
  "week_summary": "3-4 sentence summary",
  "wins": ["specific win 1", "specific win 2"],
  "concerns": ["concern 1 with specific goal reference", "concern 2"],
  "patterns": "Behavioral pattern observation or null",
  "narrative": "3-5 sentence arc connecting recent weeks, or null if fewer than 2 prior reviews",
  "next_week_focus": [
    {{"goal_id": <id or null>, "goal_title": "...", "suggestion": "specific action to take"}},
    {{"goal_id": <id or null>, "goal_title": "...", "suggestion": "specific action to take"}}
  ],
  "overall_trend": "improving|stable|declining"
}}"""

    try:
        data, _ = _call_gemini_with_retry(prompt)
    except Exception as e:
        return {"error": f"Failed to generate weekly review: {str(e)}"}

    focus_areas = data.get("next_week_focus", [])
    db.save_weekly_review(
        week_start=week_start_str,
        week_end=week_end_str,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        completion_rate=completion_rate,
        goals_progressed=goals_progressed,
        goals_neglected=goals_neglected,
        ai_review=json.dumps(data),
        focus_areas=focus_areas,
    )

    return data
