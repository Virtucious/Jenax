"""Research Agent — learning path tracking and resource suggestions."""

import re
from datetime import date, timedelta

import database as db
from agents.base import BaseAgent

_PERSONA = (
    "You are the Research Coach — a learning strategist who helps people "
    "make consistent progress on educational goals. You break down learning "
    "into daily bite-sized tasks, track progress through courses and books, "
    "and suggest resources. You believe in spaced repetition, active recall, "
    "and the power of showing up every day even for just 20 minutes."
)

_LEARNING_KEYWORDS = re.compile(
    r"\b(learn|course|book|read|study|tutorial|certification|skill|training|"
    r"practice|master|understand|explore)\b",
    re.IGNORECASE,
)


def _is_learning_goal(goal):
    text = f"{goal.get('title', '')} {goal.get('description', '')}"
    return bool(_LEARNING_KEYWORDS.search(text))


class ResearchAgent(BaseAgent):

    def __init__(self):
        super().__init__("research", _PERSONA)

    def build_context(self):
        today = date.today()
        active_goals = db.get_active_goals_flat()
        learning_goals = [g for g in active_goals if _is_learning_goal(g)]

        resources = db.get_learning_resources()
        recent_learning_tasks = db.get_recent_learning_tasks(days=7)

        return {
            "today": today.isoformat(),
            "learning_goals": learning_goals,
            "resources": resources,
            "recent_learning_tasks": recent_learning_tasks,
        }

    def build_prompt(self, context, extra_input=None):
        today = context["today"]
        learning_goals = context["learning_goals"]
        resources = context["resources"]
        recent_learning_tasks = context["recent_learning_tasks"]

        # Learning goals text
        if learning_goals:
            goal_lines = [
                f"- [{g['level'][0].upper()}] {g['title']} (id:{g['id']})"
                + (f" — due {g['deadline']}" if g.get("deadline") else "")
                for g in learning_goals
            ]
            goals_text = "\n".join(goal_lines)
        else:
            goals_text = "No learning-related goals detected."

        # Active resources text
        if resources:
            resource_lines = []
            for r in resources:
                progress_str = f"{r['completed_units']}/{r['total_units']} {r['unit_label']}s" if r.get("total_units") else "no total set"
                resource_lines.append(
                    f"- [{r['id']}] {r['title']}"
                    + (f" by {r['author']}" if r.get("author") else "")
                    + f" | Type: {r['type']} | Progress: {progress_str}"
                    + f" | Status: {r['status']}"
                    + (f" | Goal: id={r['goal_id']}" if r.get("goal_id") else "")
                    + (f" | Notes: {r['notes']}" if r.get("notes") else "")
                )
            resources_text = "\n".join(resource_lines)
        else:
            resources_text = "No learning resources tracked yet."

        # Recent learning activity
        if recent_learning_tasks:
            activity_lines = [
                f"- {t['date']}: {t['title']} ({'done' if t['completed'] else 'missed'})"
                for t in recent_learning_tasks
            ]
            activity_text = "\n".join(activity_lines)
        else:
            activity_text = "No recent learning activity."

        # Deadline proximity
        deadline_lines = []
        for g in learning_goals:
            if g.get("deadline"):
                try:
                    days_left = (date.fromisoformat(g["deadline"]) - date.today()).days
                    deadline_lines.append(f"- {g['title']}: {days_left} days remaining")
                except Exception:
                    pass
        deadline_text = "\n".join(deadline_lines) if deadline_lines else "No learning deadlines set."

        return f"""{self.persona}

## Learning Goals
{goals_text}

## Active Learning Resources
{resources_text}

## Recent Learning Activity (Last 7 Days)
{activity_text}

## Today's Date: {today}
## Days Until Goal Deadlines
{deadline_text}

## Instructions
1. For each active learning resource, suggest a specific task for today
2. Tasks should be small and completable in 20–45 minutes
3. Use spaced repetition logic: if the user studied something 2 days ago, suggest reviewing it
4. If a resource is falling behind schedule (based on deadline), flag it
5. If no resources are tracked but learning goals exist, suggest specific resources to start
6. If too many resources are in progress, suggest focusing on 1–2 at a time

Respond ONLY with valid JSON:
{{
  "learning_tasks": [
    {{
      "title": "...",
      "description": "...",
      "priority": "high|medium|low",
      "goal_id": <related goal id or null>,
      "resource_id": <related resource id or null>,
      "estimated_minutes": <number>,
      "task_type": "new_content|review|practice|project"
    }}
  ],
  "resource_suggestions": [
    {{
      "title": "Suggested resource title",
      "type": "book|course|tutorial|article|video",
      "reason": "Why this would help with their goal",
      "goal_id": <related goal id or null>
    }}
  ],
  "progress_alerts": [
    {{
      "resource_id": <id>,
      "message": "You're behind schedule — consider doing 2 units today."
    }}
  ],
  "flags": ["any notes for the orchestrator"]
}}"""
