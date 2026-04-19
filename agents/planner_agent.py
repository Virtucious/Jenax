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
        today_blueprint_units = db.get_units_scheduled_today()
        active_habits = db.get_all_habits()

        profile_block = db.get_profile_for_prompt()
        energy_curve = db.get_energy_curve()
        due_reviews = db.get_due_spaced_reviews(today.isoformat(), limit=2)
        capacity = db.calculate_daily_capacity(today)

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
            "today_blueprint_units": today_blueprint_units,
            "active_habits": active_habits,
            "profile_block": profile_block,
            "energy_curve": energy_curve,
            "due_reviews": due_reviews,
            "capacity": capacity,
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
        today_blueprint_units = context.get("today_blueprint_units", [])
        active_habits = context.get("active_habits", [])
        profile_block = context.get("profile_block", "")
        energy_curve = context.get("energy_curve", {})
        due_reviews = context.get("due_reviews", [])
        capacity = context.get("capacity", {})

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

        # Blueprint context: group today's units by blueprint
        blueprint_context = ""
        if today_blueprint_units or active_habits:
            blueprint_context = "\n\n## Active Blueprints"
            # Group units by blueprint
            by_blueprint = {}
            for u in today_blueprint_units:
                bp_id = u.get("blueprint_id")
                if bp_id not in by_blueprint:
                    by_blueprint[bp_id] = {
                        "goal_title": u.get("goal_title", ""),
                        "blueprint_type": u.get("blueprint_type", ""),
                        "unit_label": u.get("unit_label", "unit"),
                        "estimated_pace": u.get("estimated_pace_minutes"),
                        "actual_pace": u.get("actual_pace_minutes"),
                        "units": [],
                    }
                by_blueprint[bp_id]["units"].append(u)

            for bp_id, bp_data in by_blueprint.items():
                bp_type = bp_data["blueprint_type"]
                unit_label = bp_data["unit_label"]
                est_pace = bp_data["estimated_pace"]
                act_pace = bp_data["actual_pace"]
                pace_str = ""
                if act_pace:
                    pace_str = f"estimated {est_pace or '?'}min/{unit_label}, actual {act_pace:.0f}min/{unit_label}"
                elif est_pace:
                    pace_str = f"estimated {est_pace}min/{unit_label}"

                blueprint_context += f"\n\n### Blueprint: \"{bp_data['goal_title']}\" ({bp_type})"
                if pace_str:
                    blueprint_context += f"\nPace: {pace_str}"

                blueprint_context += f"\nToday's scheduled units:"
                for u in bp_data["units"]:
                    meta_str = ""
                    if u.get("metadata"):
                        try:
                            meta = json.loads(u["metadata"]) if isinstance(u["metadata"], str) else u["metadata"]
                            parts = []
                            if meta.get("page_range"):
                                parts.append(f"pp. {meta['page_range']}")
                            if meta.get("exercises"):
                                parts.append(f"exercises: {', '.join(meta['exercises'])}")
                            if parts:
                                meta_str = " | " + " | ".join(parts)
                        except Exception:
                            pass
                    eff_min = (act_pace or est_pace or u.get("estimated_minutes") or 30)
                    diff_str = f" | {u['difficulty']:.1f}x difficulty" if u.get("difficulty") and u["difficulty"] != 1.0 else ""
                    blueprint_context += (
                        f"\n  - Unit #{u['unit_number']} (id:{u['id']}): \"{u['title']}\""
                        f"\n    Estimated: {eff_min:.0f}min{diff_str}{meta_str}"
                    )
                    if u.get("description"):
                        blueprint_context += f"\n    Description: {u['description']}"

            # Habits scheduled today
            if active_habits:
                from datetime import datetime as _dt
                today_dow = _dt.today().isoweekday()  # 1=Mon … 7=Sun
                for h in active_habits:
                    freq = h.get("frequency", "daily")
                    custom_days = h.get("custom_days")
                    scheduled = False
                    if freq == "daily":
                        scheduled = True
                    elif freq == "weekdays":
                        scheduled = today_dow <= 5
                    elif freq == "weekends":
                        scheduled = today_dow >= 6
                    elif freq == "custom" and custom_days:
                        try:
                            days = json.loads(custom_days) if isinstance(custom_days, str) else custom_days
                            scheduled = today_dow in days
                        except Exception:
                            pass
                    if not scheduled:
                        continue
                    prog_type = h.get("progression_type", "constant")
                    qty = h.get("current_quantity")
                    unit = h.get("quantity_unit", "")
                    target = h.get("target_quantity")
                    blueprint_context += f"\n\n### Habit: \"{h.get('goal_title', h.get('blueprint_title', ''))}\" (habit)"
                    blueprint_context += f"\nFrequency: {freq}"
                    blueprint_context += f"\nToday's target: {qty} {unit}"
                    if prog_type == "progressive" and target:
                        blueprint_context += f" (progressive → {target} {unit})"

        # Spaced reviews context
        reviews_context = ""
        if due_reviews:
            reviews_context = "\n\n## Scheduled Reviews for Today (Spaced Repetition)"
            reviews_context += "\nCap at 2 review tasks. These are low-energy, short recall exercises."
            for r in due_reviews:
                days_since = ""
                try:
                    from datetime import date as _d2
                    completed_unit = db.get_blueprint_unit(r["blueprint_unit_id"])
                    if completed_unit and completed_unit.get("completed_at"):
                        delta = (_d2.today() - _d2.fromisoformat(completed_unit["completed_at"][:10])).days
                        days_since = f" | {delta} days since completion"
                except Exception:
                    pass
                meta_hint = ""
                try:
                    meta = json.loads(r["unit_metadata"]) if r.get("unit_metadata") else {}
                    parts = []
                    if meta.get("page_range"):
                        parts.append(f"pp. {meta['page_range']}")
                    if meta.get("exercises"):
                        parts.append(f"exercises: {', '.join(meta['exercises'])}")
                    if parts:
                        meta_hint = " | " + " | ".join(parts)
                except Exception:
                    pass
                reviews_context += (
                    f"\n- [spaced_review_id:{r['id']}] Review #{r['review_number']}: "
                    f"\"{r['unit_title']}\" from {r['blueprint_title']}{days_since}{meta_hint}"
                )

        blueprint_task_rules = ""
        # Energy curve section
        _slot_times = [
            ("slot_1", "6–9 AM"),
            ("slot_2", "9–12 PM"),
            ("slot_3", "12–3 PM"),
            ("slot_4", "3–6 PM"),
            ("slot_5", "6–9 PM"),
        ]
        _emoji_map = {"high": "⚡", "medium": "☕", "low": "🌿"}
        ec_lines = []
        for slot_key, time_range in _slot_times:
            label = energy_curve.get(f"{slot_key}_label", slot_key.replace("_", " ").title())
            energy = energy_curve.get(f"{slot_key}_energy", "medium")
            emoji = _emoji_map.get(energy, "☕")
            ec_lines.append(f"{label} ({time_range}): {emoji} {energy} energy")
        energy_curve_section = "\n\n## Energy Curve (Your Day)\n" + "\n".join(ec_lines) + """

Sequencing rules:
- Match task energy_level to available slots: ⚡ high → high-energy slots, ☕ medium → medium, 🌿 low → low
- Never stack more than 2 high-energy tasks consecutively
- After a high-energy task, include a low-energy task for recovery
- Assign each task a suggested_slot name (e.g. "Morning (9-12)") as a recommendation, not a rigid schedule"""

        # Capacity section
        capacity_section = ""
        capacity_rules = ""
        if capacity:
            cap_total = capacity.get("total_capacity_minutes", 240)
            cap_already = capacity.get("already_scheduled_minutes", 0)
            cap_remaining = capacity.get("remaining_minutes", cap_total)
            cap_quality = capacity.get("day_quality", "medium")
            cap_notes = capacity.get("notes") or ""
            capacity_section = f"\n\n## Today's Capacity Assessment"
            capacity_section += f"\nTotal capacity: {cap_total} min ({cap_quality} day)"
            capacity_section += f"\nAlready scheduled: {cap_already} min"
            capacity_section += f"\nRemaining capacity: {cap_remaining} min"
            if cap_notes:
                capacity_section += f"\nNotes: {cap_notes}"

            _low_cap = cap_remaining < 60
            _recovery = "Recovery day" in cap_notes
            cap_rule_lines = [
                f"- Total task time MUST NOT exceed remaining capacity ({cap_remaining} min)",
            ]
            if _low_cap:
                cap_rule_lines.append("- Remaining capacity is very low — generate only 1-2 small tasks")
            if _recovery:
                cap_rule_lines.append("- Recovery day: reduce load by 40%, avoid high-energy tasks")
            if cap_quality == "low":
                cap_rule_lines.append("- Low-quality day: prefer low-energy, low-stakes tasks")
            capacity_rules = "\n\nCapacity rules:\n" + "\n".join(cap_rule_lines)

        if today_blueprint_units or active_habits:
            blueprint_task_rules = """
9. For LEARNING blueprints: reference specific chapters, page ranges, and exercises. Include the blueprint_unit_id from the unit's id field.
10. For CAREER blueprints: specify how many applications/actions, criteria, and phase. Include blueprint_unit_id.
11. For HABIT blueprints: use the exact current target quantity and unit. Keep description motivational.
12. ALWAYS include blueprint_unit_id in your response when a task corresponds to a blueprint unit so the system can mark units complete when the task is done."""

        review_task_rules = ""
        if due_reviews:
            review_task_rules = """
13. For REVIEW tasks (from Scheduled Reviews): set task_type="review", energy_level="low", estimated_minutes=5-10. Include spaced_review_id. Description should prompt active recall: "Without looking at your notes, recall 3 key ideas from this unit. Then check." Never exceed 2 review tasks."""

        carry_rule = ""
        if carried_tasks:
            heavy = [t for t in carried_tasks if (t.get("carry_count") or 0) >= 3]
            if heavy:
                carry_rule = "\n9. Tasks carried 3+ times should be flagged in daily_insight as needing to be broken down or reconsidered."

        profile_section = f"\n{profile_block}\n" if profile_block else ""

        return f"""{self.persona}
{profile_section}
## User's Active Goals
{goals_text}

## Recent Task History (Last 7 Days)
{history_text}{existing_text}{extra_context}{blueprint_context}{reviews_context}{energy_curve_section}{capacity_section}{agent_inputs_text}

## Rules
1. Generate 5-8 tasks maximum. Less is better.
2. Each task must be concrete and completable in one sitting (30min–2hrs).
3. Sequence tasks by energy: hardest/most important in positions 1–3.
4. Include 1 quick win (under 15 minutes).
5. If other agents flagged items, integrate them — don't just append.
6. If a task has been carried forward 3+ times, either break it smaller or recommend dropping it.
7. Total estimated time MUST NOT exceed remaining capacity (see Today's Capacity Assessment above).
8. If it's a historically low-completion day, generate fewer tasks (4–5 instead of 7–8).{carry_rule}{blueprint_task_rules}{review_task_rules}{capacity_rules}

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
      "suggested_slot": "Slot name (time range)",
      "sequence_position": <1-based integer>,
      "sequence_reason": "Why this task is in this position",
      "blueprint_unit_id": <id or null>,
      "task_type": "normal|review",
      "spaced_review_id": <id or null>
    }}
  ],
  "daily_insight": "One sentence of strategic advice",
  "workload_assessment": "light|moderate|heavy",
  "flags": ["any warnings or notes for the orchestrator"]
}}"""
