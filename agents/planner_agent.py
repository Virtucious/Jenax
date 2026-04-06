"""Planner Agent — daily task generation specialist."""

import json
from datetime import date, timedelta

import database as db
from agents.base import BaseAgent

_PERSONA = (
    "You are the Planner — a focused productivity strategist. Your job is to "
    "create realistic, prioritized daily task lists. You think in terms of "
    "energy management, task sequencing, and momentum. You front-load important "
    "work and protect the user from overcommitting."
)


class PlannerAgent(BaseAgent):

    def __init__(self):
        super().__init__("planner", _PERSONA)

    def build_context(self):
        today = date.today()
        yesterday = (today - timedelta(days=1)).isoformat()
        week_start = (today - timedelta(days=today.weekday())).isoformat()

        active_goals = db.get_active_goals_flat()
        history = db.get_recent_task_history(days=7)
        today_tasks = db.get_tasks_for_date(today.isoformat())
        yesterday_reflection = db.get_reflection_for_date(yesterday)
        last_weekly_review = db.get_previous_weekly_review(week_start)
        carried_tasks = [t for t in today_tasks if t.get("is_carried")]
        dow_patterns = db.get_day_of_week_patterns()
        pending_email_items = db.get_pending_email_action_items(today.isoformat())

        return {
            "today": today.isoformat(),
            "day_name": today.strftime("%A"),
            "active_goals": active_goals,
            "history": history,
            "today_tasks": today_tasks,
            "yesterday_reflection": yesterday_reflection,
            "last_weekly_review": last_weekly_review,
            "carried_tasks": carried_tasks,
            "dow_patterns": dow_patterns,
            "pending_email_items": pending_email_items,
        }

    def build_prompt(self, context, extra_input=None):
        today = context["today"]
        day_name = context["day_name"]
        active_goals = context["active_goals"]
        history = context["history"]
        today_tasks = context["today_tasks"]
        yesterday_reflection = context["yesterday_reflection"]
        last_weekly_review = context["last_weekly_review"]
        carried_tasks = context["carried_tasks"]
        dow_patterns = context["dow_patterns"]
        pending_email_items = context["pending_email_items"]

        # Goal hierarchy text
        yearly = [g for g in active_goals if g["level"] == "yearly"]
        monthly = [g for g in active_goals if g["level"] == "monthly"]
        weekly = [g for g in active_goals if g["level"] == "weekly"]

        goal_lines = []
        for yg in yearly:
            goal_lines.append(f"- [Y] {yg['title']} (id:{yg['id']})"
                              + (f" — due {yg['deadline']}" if yg.get("deadline") else ""))
            for mg in monthly:
                if mg["parent_id"] == yg["id"]:
                    goal_lines.append(f"  - [M] {mg['title']} (id:{mg['id']})")
                    for wg in weekly:
                        if wg["parent_id"] == mg["id"]:
                            goal_lines.append(f"    - [W] {wg['title']} (id:{wg['id']})")
        for mg in monthly:
            if not any(mg["parent_id"] == yg["id"] for yg in yearly):
                goal_lines.append(f"- [M] {mg['title']} (id:{mg['id']})")
                for wg in weekly:
                    if wg["parent_id"] == mg["id"]:
                        goal_lines.append(f"  - [W] {wg['title']} (id:{wg['id']})")

        goals_text = "\n".join(goal_lines) if goal_lines else "No goals set yet."

        # History text
        history_lines = []
        for h in history:
            titles = ", ".join(h["completed_titles"]) if h["completed_titles"] else "none"
            history_lines.append(
                f"- {h['date']}: {h['completed_count'] or 0}/{h['total']} completed — {titles}"
            )
        history_text = "\n".join(history_lines) if history_lines else "No recent history."

        # Already planned today
        existing_text = ""
        if today_tasks:
            existing_text = "\n\n## Already Planned for Today\n" + "\n".join(
                f"- {'[done]' if t['completed'] else '[todo]'} {t['title']}" for t in today_tasks
            )

        extra_context = ""

        # Yesterday's reflection
        if yesterday_reflection:
            summary = yesterday_reflection.get("ai_summary") or ""
            tomorrow_suggestions = []
            try:
                parsed = json.loads(summary)
                summary_text = parsed.get("reflection", summary)
                tomorrow_suggestions = parsed.get("tomorrow_suggestions", [])
            except Exception:
                summary_text = summary
            extra_context += f"\n\n## Yesterday's Review\n{summary_text}"
            if tomorrow_suggestions:
                extra_context += "\nSuggestions for today: " + "; ".join(tomorrow_suggestions)

        # Weekly focus areas
        if last_weekly_review and last_weekly_review.get("focus_areas"):
            focus = last_weekly_review["focus_areas"]
            if isinstance(focus, list):
                lines = []
                for item in focus:
                    if isinstance(item, dict):
                        lines.append(f"- {item.get('goal_title', '')}: {item.get('suggestion', '')}")
                    else:
                        lines.append(f"- {item}")
                extra_context += "\n\n## This Week's Focus Areas\n" + "\n".join(lines)

        # Carried tasks
        if carried_tasks:
            extra_context += "\n\n## Carried Forward from Yesterday\n" + "\n".join(
                f"- {t['title']} (carried {t.get('carry_count', 1)} time(s))"
                for t in carried_tasks
            )

        # Day-of-week patterns
        if dow_patterns:
            pattern_lines = [f"{p['day_name']}: ~{p['avg_pct']}% avg" for p in dow_patterns if p.get("avg_pct")]
            today_pattern = next((p for p in dow_patterns if p["day_name"] == day_name), None)
            if pattern_lines:
                extra_context += "\n\n## Day-of-Week Patterns\n" + "\n".join(pattern_lines)
                if today_pattern:
                    extra_context += f"\nToday is {day_name} (historically ~{today_pattern['avg_pct']}% completion)."

        # Pending email items from DB (pre-existing)
        if pending_email_items:
            item_lines = [
                f"- [{i['priority']}] {i['title']} (from: {i.get('source_sender', '?')})"
                for i in pending_email_items
            ]
            extra_context += "\n\n## Pending Email Action Items\n" + "\n".join(item_lines)

        # Agent inputs from orchestrator
        agent_inputs_text = ""
        if extra_input:
            email_actions = extra_input.get("email_actions", [])
            learning_tasks = extra_input.get("learning_tasks", [])
            accountability_warnings = extra_input.get("accountability_warnings", [])

            if email_actions:
                agent_inputs_text += "\n\n## Email Agent: Prioritized Inbox Actions\n" + "\n".join(
                    f"- {a}" for a in email_actions
                )
            if learning_tasks:
                agent_inputs_text += "\n\n## Research Agent: Learning Tasks\n" + "\n".join(
                    f"- {t}" for t in learning_tasks
                )
            if accountability_warnings:
                agent_inputs_text += "\n\n## Accountability Agent: Warnings\n" + "\n".join(
                    f"- {w}" for w in accountability_warnings
                )

        carry_rule = ""
        if carried_tasks:
            heavy = [t for t in carried_tasks if (t.get("carry_count") or 0) >= 3]
            if heavy:
                carry_rule = "\n9. Tasks carried 3+ times should be flagged in daily_insight as needing to be broken down or reconsidered."

        return f"""{self.persona}

## User's Active Goals
{goals_text}

## Recent Task History (Last 7 Days)
{history_text}{existing_text}{extra_context}{agent_inputs_text}

## Rules
1. Generate 5-8 tasks maximum. Less is better.
2. Each task must be concrete and completable in one sitting (30min–2hrs).
3. Sequence tasks by energy: hardest/most important in positions 1–3.
4. Include 1 quick win (under 15 minutes).
5. If other agents flagged items, integrate them — don't just append.
6. If a task has been carried forward 3+ times, either break it smaller or recommend dropping it.
7. Total estimated time should not exceed 6 hours of focused work.
8. If it's a historically low-completion day, generate fewer tasks (4–5 instead of 7–8).{carry_rule}

Respond ONLY with valid JSON:
{{
  "tasks": [
    {{
      "title": "...",
      "description": "...",
      "priority": "high|medium|low",
      "goal_id": <id or null>,
      "estimated_minutes": <number>,
      "energy_level": "high|medium|low",
      "sequence_reason": "Why this task is in this position"
    }}
  ],
  "daily_insight": "One sentence of strategic advice",
  "workload_assessment": "light|moderate|heavy",
  "flags": ["any warnings or notes for the orchestrator"]
}}"""
