"""LLM-based email summarization and action item extraction."""

import json
import re

from google import genai

from config import GEMINI_API_KEY

_MODEL = "gemini-3-flash-preview"


def _get_client():
    return genai.Client(api_key=GEMINI_API_KEY)


def _parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def process_emails(emails):
    """
    Summarize emails and extract action items using Gemini.

    Returns:
        {
            "summary": "...",
            "action_items": [...],
            "categories": {"needs_reply": N, "informational": N, "action_required": N, "can_ignore": N}
        }
    """
    if not emails:
        return {
            "summary": "No new emails in the last 24 hours.",
            "action_items": [],
            "categories": {"needs_reply": 0, "informational": 0, "action_required": 0, "can_ignore": 0},
        }

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

    prompt = f"""You are an executive assistant reviewing someone's recent emails. Your job is to:
1. Provide a brief summary of the inbox
2. Extract concrete action items that the user needs to do
3. Categorize the emails

## Recent Emails (last 24 hours)

{emails_text}

## Instructions

1. **Summary**: Write a 2-4 sentence overview of the inbox. Mention any urgent items first. Group related emails together (e.g., "3 emails about Project X").

2. **Action Items**: Extract tasks the user needs to actually DO. Rules:
   - Only include items that require the user's action (reply, review, complete, decide, attend)
   - Do NOT include informational emails, newsletters, or notifications
   - Each action item should be a concrete, completable task
   - Set priority based on urgency and importance:
     - high: has a deadline soon, someone is waiting, or it's from a boss/important contact
     - medium: needs to be done but not urgent
     - low: nice to do, optional, or low-stakes

3. **Categories**: Count how many emails fall into each bucket:
   - needs_reply: someone asked a question or is waiting for a response
   - action_required: requires the user to do something other than reply
   - informational: FYI, updates, newsletters, no action needed
   - can_ignore: automated notifications, marketing, spam-adjacent

Respond ONLY with valid JSON:
{{
  "summary": "2-4 sentence inbox summary",
  "action_items": [
    {{
      "title": "Short action-oriented task title",
      "description": "1-2 sentences on what exactly to do and why",
      "priority": "high|medium|low",
      "source_subject": "Original email subject line",
      "source_sender": "Sender name"
    }}
  ],
  "categories": {{
    "needs_reply": <number>,
    "informational": <number>,
    "action_required": <number>,
    "can_ignore": <number>
  }}
}}

If there are no action items, return an empty array for action_items.
If there are no emails, return a summary saying "No new emails in the last 24 hours.\""""

    client = _get_client()
    response = client.models.generate_content(model=_MODEL, contents=prompt)
    text = response.text

    try:
        return _parse_json(text)
    except json.JSONDecodeError:
        retry_prompt = prompt + "\n\nIMPORTANT: Respond ONLY with valid JSON. No other text."
        response = client.models.generate_content(model=_MODEL, contents=retry_prompt)
        return _parse_json(response.text)
