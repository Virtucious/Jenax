"""Base agent class — shared Gemini call, logging, and JSON parsing."""

import json
import re
import time

from google import genai

import database as db
from config import GEMINI_API_KEY

_MODEL = "gemini-2.5-flash"


class BaseAgent:
    """Base class for all jenax agents."""

    def __init__(self, name, persona):
        """
        name:    agent identifier ('planner', 'email', 'research', 'accountability')
        persona: opening line of the system prompt describing who this agent is
        """
        self.name = name
        self.persona = persona

    def _client(self):
        return genai.Client(api_key=GEMINI_API_KEY)

    def build_context(self):
        """Override in subclass. Returns dict of context data."""
        raise NotImplementedError

    def build_prompt(self, context, extra_input=None):
        """Override in subclass. Returns string prompt."""
        raise NotImplementedError

    def parse_response(self, raw_text):
        """Parse raw LLM text as JSON. Strips markdown code fences."""
        cleaned = raw_text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        return json.loads(cleaned)

    def run(self, extra_input=None, trigger_type="manual"):
        """
        Execute the agent:
        1. Build context
        2. Build prompt
        3. Call Gemini
        4. Parse response
        5. Log everything
        Returns parsed output dict.
        """
        start = time.time()
        context = self.build_context()
        prompt = self.build_prompt(context, extra_input)

        try:
            client = self._client()
            response = client.models.generate_content(model=_MODEL, contents=prompt)
            raw_text = response.text
            try:
                parsed = self.parse_response(raw_text)
            except json.JSONDecodeError:
                # One retry with explicit JSON instruction
                retry_prompt = prompt + "\n\nIMPORTANT: Respond ONLY with valid JSON. No other text."
                response = client.models.generate_content(model=_MODEL, contents=retry_prompt)
                raw_text = response.text
                parsed = self.parse_response(raw_text)

            duration_ms = int((time.time() - start) * 1000)
            self._log(
                trigger_type=trigger_type,
                input_summary=self._summarize_context(context),
                raw_prompt=prompt,
                raw_response=raw_text,
                parsed_output=json.dumps(parsed),
                duration_ms=duration_ms,
                success=True,
                error_message=None,
            )
            return parsed

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log(
                trigger_type=trigger_type,
                input_summary=self._summarize_context(context),
                raw_prompt=prompt,
                raw_response=str(e),
                parsed_output=None,
                duration_ms=duration_ms,
                success=False,
                error_message=str(e),
            )
            raise

    def _log(self, trigger_type, input_summary, raw_prompt, raw_response,
             parsed_output, duration_ms, success, error_message):
        """Save agent run to agent_logs table."""
        conn = db.get_connection()
        with conn:
            conn.execute(
                """INSERT INTO agent_logs
                   (agent_name, trigger_type, input_summary, raw_prompt,
                    raw_response, parsed_output, duration_ms, success, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (self.name, trigger_type, input_summary, raw_prompt,
                 raw_response, parsed_output, duration_ms, int(success), error_message),
            )
        conn.close()

    def _summarize_context(self, context):
        return f"{len(str(context))} chars of context"
