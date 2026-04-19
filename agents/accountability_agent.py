"""Accountability Agent — behavioral patterns, goal health, and nudges."""

import json
from datetime import date, timedelta

import database as db
from agents.base import BaseAgent

_PERSONA = (
    "You are the Accountability Partner — a supportive but honest coach who "
    "tracks behavioral patterns over time. You notice when someone is "
    "avoiding certain goals, when their productivity is declining, and when "
    "they deserve celebration. You don't lecture — you observe, ask good "
    "questions, and nudge gently. But you don't let important things slide."
)


class AccountabilityAgent(BaseAgent):

    def __init__(self):
        super().__init__("accountability", _PERSONA)

    def build_context(self):
        today = date.today()

        active_goals = db.get_active_goals_flat()
        history_30 = db.get_recent_task_history(days=30)
        progress = db.get_progress_data(days=30)
        reflections = db.get_recent_reflections(days=14)
        previous_insights = db.get_active_insights(limit=5)

        # Goal activity map: last task completed date per goal
        goal_activity = db.get_goal_last_activity()

        # Day-of-week patterns
        dow_patterns = db.get_day_of_week_patterns()

        profile_block = db.get_profile_for_prompt()

        return {
            "today": today.isoformat(),
            "active_goals": active_goals,
            "history_30": history_30,
            "progress": progress,
            "reflections": reflections,
            "previous_insights": previous_insights,
            "goal_activity": goal_activity,
            "dow_patterns": dow_patterns,
            "profile_block": profile_block,
        }

    def build_prompt(self, context, extra_input=None):
        today = context["today"]
        active_goals = context["active_goals"]
        history_30 = context["history_30"]
        progress = context["progress"]
        reflections = context["reflections"]
        previous_insights = context["previous_insights"]
        goal_activity = context["goal_activity"]
        dow_patterns = context["dow_patterns"]
        profile_block = context.get("profile_block", "")

        # Goal health report
        goal_lines = []
        for g in active_goals:
            last_activity = goal_activity.get(g["id"])
            if last_activity:
                delta = (date.today() - date.fromisoformat(last_activity)).days
                last_str = f"{last_activity} ({delta} days ago)"
            else:
                last_str = "never"

            goal_lines.append(
                f"Goal: {g['title']} (level: {g['level']}, id: {g['id']}"
                + (f", deadline: {g['deadline']}" if g.get("deadline") else "")
                + f")\n  Status: {g['status']}\n  Last task completed: {last_str}"
            )
        goals_text = "\n\n".join(goal_lines) if goal_lines else "No active goals."

        # 30-day completion trend
        trend_lines = []
        for h in reversed(history_30):
            pct = round((h.get("completed_count") or 0) / h["total"] * 100) if h["total"] else 0
            trend_lines.append(f"- {h['date']}: {h.get('completed_count', 0)}/{h['total']} ({pct}%)")
        trend_text = "\n".join(trend_lines) if trend_lines else "No data."

        # Day-of-week averages
        dow_text = ", ".join(
            f"{p['day_name'][:3]}: {p['avg_pct']}%"
            for p in dow_patterns if p.get("avg_pct")
        ) or "No pattern data."

        # Streaks
        current_streak = progress.get("current_streak", 0)
        longest_streak = progress.get("longest_streak", 0)

        # Mood trend
        mood_lines = []
        for r in reflections:
            if r.get("mood"):
                mood_lines.append(f"- {r['date']}: {r['mood']}")
        mood_text = "\n".join(mood_lines) if mood_lines else "No mood data."

        # Previous insights (to avoid repeating)
        prev_lines = []
        for ins in previous_insights:
            prev_lines.append(f"- [{ins['insight_type']}] {ins['title']} (created: {ins['created_at'][:10]})")
        prev_text = "\n".join(prev_lines) if prev_lines else "None."

        profile_section = f"\n{profile_block}\n" if profile_block else ""

        return f"""{self.persona}
{profile_section}
## Goal Health Report
{goals_text}

## 30-Day Completion Trend
{trend_text}

## Behavioral Patterns
Day-of-week averages: {dow_text}
Best streak: {longest_streak} days
Current streak: {current_streak} days

## Previous Insights (avoid repeating these)
{prev_text}

## Recent Mood Trend (Last 14 Days)
{mood_text}

## Instructions
1. Identify 2-4 insights about the user's productivity patterns
2. Each insight should be one of:
   - "pattern": a recurring behavior (good or bad)
   - "warning": a goal or habit that's at risk
   - "nudge": a gentle push toward something being avoided
   - "celebration": recognition of progress or consistency
3. Be specific — reference actual goals, dates, and numbers
4. Don't repeat insights from the "Previous Insights" section
5. If mood has been declining, note it sensitively
6. Set valid_days: patterns → 14, warnings → 7, celebrations → 3
7. Assign severity: info (observations), warning (needs attention), critical (goal at serious risk)

Respond ONLY with valid JSON:
{{
  "insights": [
    {{
      "type": "pattern|warning|nudge|celebration",
      "title": "Short title",
      "description": "2-3 sentence observation with specific data",
      "related_goal_id": <goal id or null>,
      "severity": "info|warning|critical",
      "valid_days": <number>,
      "suggested_action": "What the user could do, or null for celebrations"
    }}
  ],
  "overall_health": "thriving|steady|struggling|critical",
  "flags": ["any urgent notes for the orchestrator"]
}}"""
