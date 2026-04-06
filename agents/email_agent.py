"""Email Agent — inbox triage and action extraction specialist."""

import json
from datetime import date, timedelta

import database as db
from agents.base import BaseAgent

_PERSONA = (
    "You are the Email Analyst — an executive assistant who triages inboxes "
    "with precision. You distinguish between truly urgent items and things "
    "that just feel urgent. You protect the user's focus by being ruthlessly "
    "selective about what deserves their attention."
)


class EmailAgent(BaseAgent):

    def __init__(self):
        super().__init__("email", _PERSONA)

    def build_context(self):
        today = date.today().isoformat()
        active_goals = db.get_active_goals_flat()
        today_tasks = db.get_tasks_for_date(today)

        # Last 3 days of digests for thread context
        recent_digests = []
        for i in range(1, 4):
            d = (date.today() - timedelta(days=i)).isoformat()
            digest = db.get_email_digest_for_date(d)
            if digest:
                recent_digests.append({"date": d, "summary": digest.get("ai_summary", "")})

        return {
            "today": today,
            "emails": [],  # will be populated via extra_input
            "active_goals": active_goals,
            "today_tasks": today_tasks,
            "recent_digests": recent_digests,
        }

    def build_prompt(self, context, extra_input=None):
        emails = []
        if extra_input and "emails" in extra_input:
            emails = extra_input["emails"]

        active_goals = context["active_goals"]
        today_tasks = context["today_tasks"]
        recent_digests = context["recent_digests"]

        # Email blocks
        if emails:
            email_blocks = []
            for e in emails:
                block = (
                    f"---\n"
                    f"From: {e.get('sender', 'Unknown')}\n"
                    f"Subject: {e.get('subject', '(no subject)')}\n"
                    f"Date: {e.get('date', '')}\n"
                    f"Body: {e.get('body') or e.get('snippet', '')}\n"
                    f"---"
                )
                email_blocks.append(block)
            emails_text = "\n\n".join(email_blocks)
        else:
            emails_text = "No emails provided."

        # Goals text
        goals_lines = [
            f"- [{g['level'][0].upper()}] {g['title']} (id:{g['id']})"
            for g in active_goals
        ]
        goals_text = "\n".join(goals_lines) if goals_lines else "No active goals."

        # Today's tasks
        tasks_text = "\n".join(
            f"- {t['title']}" for t in today_tasks
        ) if today_tasks else "No tasks yet today."

        # Previous digests
        digest_lines = []
        for d in recent_digests:
            if d.get("summary"):
                digest_lines.append(f"- {d['date']}: {d['summary'][:150]}")
        digests_text = "\n".join(digest_lines) if digest_lines else "No previous digests."

        return f"""{self.persona}

## Recent Emails (Last 24 Hours)
{emails_text}

## User's Current Priorities
Active goals:
{goals_text}

Today's tasks:
{tasks_text}

## Previous Digests (Context)
{digests_text}

## Instructions
1. Categorize each email: needs_reply, action_required, informational, can_ignore
2. Extract action items ONLY for things that genuinely require the user's effort
3. For "needs_reply" emails, draft a 1-2 sentence reply suggestion
4. Prioritize emails that relate to the user's active goals
5. Flag any email threads that have been going back and forth without resolution
6. If an email is from an unknown sender about something important, note it

Respond ONLY with valid JSON:
{{
  "summary": "2-4 sentence inbox overview",
  "action_items": [
    {{
      "title": "...",
      "description": "...",
      "priority": "high|medium|low",
      "source_subject": "...",
      "source_sender": "...",
      "suggested_reply": "Draft reply if needs_reply, or null",
      "related_goal_id": <goal id or null>,
      "urgency_reason": "Why this priority level"
    }}
  ],
  "categories": {{
    "needs_reply": <number>,
    "action_required": <number>,
    "informational": <number>,
    "can_ignore": <number>
  }},
  "thread_alerts": [
    {{
      "subject": "...",
      "message": "This thread has had 5 back-and-forth emails — consider scheduling a call"
    }}
  ],
  "flags": ["any notes for the orchestrator"]
}}"""
