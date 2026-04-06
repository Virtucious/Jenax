"""Orchestrator — coordinates all agents and merges their outputs."""

import logging
import re
from datetime import date, timedelta

import database as db
from agents.planner_agent import PlannerAgent
from agents.email_agent import EmailAgent
from agents.research_agent import ResearchAgent, _is_learning_goal
from agents.accountability_agent import AccountabilityAgent

logger = logging.getLogger(__name__)

_LEARNING_KEYWORDS = re.compile(
    r"\b(learn|course|book|read|study|tutorial|certification|skill|training|"
    r"practice|master|understand|explore)\b",
    re.IGNORECASE,
)


def _is_gmail_connected():
    """Check if Gmail OAuth token exists."""
    try:
        import gmail_client
        status = gmail_client.is_connected()
        return status.get("connected", False)
    except Exception:
        return False


def _has_learning_goals():
    """Check if any active goals involve learning."""
    try:
        goals = db.get_active_goals_flat()
        return any(_is_learning_goal(g) for g in goals)
    except Exception:
        return False


def _accountability_ran_recently():
    """Return True if accountability agent ran successfully within the last 6 hours."""
    try:
        log = db.get_latest_agent_log("accountability")
        if not log or not log.get("success"):
            return False
        from datetime import datetime
        last_run = datetime.fromisoformat(log["created_at"])
        age = datetime.utcnow() - last_run
        return age.total_seconds() < 6 * 3600
    except Exception:
        return False


class Orchestrator:
    """
    Coordinates all agents and produces a unified daily plan.
    This is NOT an LLM agent — it's procedural Python code.
    """

    def __init__(self):
        self.planner = PlannerAgent()
        self.email_agent = EmailAgent()
        self.research_agent = ResearchAgent()
        self.accountability_agent = AccountabilityAgent()

    def generate_daily_plan(self):
        """
        Full daily plan generation pipeline.
        Agents run in sequence; each output feeds into the next.
        Returns merged plan dict.
        """
        results = {}

        # Step 1: Accountability (runs first to provide warnings to planner)
        # Skip if it ran recently (cached result is reused)
        if _accountability_ran_recently():
            logger.info("Accountability agent: using cached result from last 6h")
            cached = db.get_latest_agent_log("accountability")
            if cached and cached.get("parsed_output"):
                import json
                try:
                    results["accountability"] = json.loads(cached["parsed_output"])
                except Exception:
                    results["accountability"] = None
            else:
                results["accountability"] = None
        else:
            try:
                results["accountability"] = self.accountability_agent.run(
                    trigger_type="orchestrated"
                )
                self._save_insights(results["accountability"])
            except Exception as e:
                logger.warning(f"Accountability agent failed: {e}")
                results["accountability"] = None

        # Step 2: Email triage (if Gmail connected)
        if _is_gmail_connected():
            try:
                import gmail_client
                emails = gmail_client.fetch_recent_emails(hours=24, max_results=50) or []
                results["email"] = self.email_agent.run(
                    extra_input={"emails": emails},
                    trigger_type="orchestrated",
                )
            except Exception as e:
                logger.warning(f"Email agent failed: {e}")
                results["email"] = None
        else:
            results["email"] = None

        # Step 3: Research tasks (if learning goals exist)
        if _has_learning_goals():
            try:
                results["research"] = self.research_agent.run(
                    trigger_type="orchestrated"
                )
            except Exception as e:
                logger.warning(f"Research agent failed: {e}")
                results["research"] = None
        else:
            results["research"] = None

        # Step 4: Planner (receives outputs from all other agents)
        agent_inputs = {
            "email_actions": self._extract_email_actions(results.get("email")),
            "learning_tasks": self._extract_learning_tasks(results.get("research")),
            "accountability_warnings": self._extract_warnings(results.get("accountability")),
        }

        results["planner"] = self.planner.run(
            extra_input=agent_inputs,
            trigger_type="orchestrated",
        )
        # Planner failure is critical — raises and triggers legacy fallback in planner.py

        return self._merge_outputs(results)

    def _merge_outputs(self, results):
        planner_output = results.get("planner", {})
        email_output = results.get("email")
        research_output = results.get("research")
        accountability_output = results.get("accountability")

        return {
            "tasks": planner_output.get("tasks", []),
            "daily_insight": planner_output.get("daily_insight", ""),
            "workload_assessment": planner_output.get("workload_assessment", "moderate"),

            "email_summary": email_output.get("summary") if email_output else None,
            "email_action_items": email_output.get("action_items", []) if email_output else [],
            "thread_alerts": email_output.get("thread_alerts", []) if email_output else [],

            "learning_tasks": research_output.get("learning_tasks", []) if research_output else [],
            "resource_suggestions": research_output.get("resource_suggestions", []) if research_output else [],
            "progress_alerts": research_output.get("progress_alerts", []) if research_output else [],

            "accountability_insights": accountability_output.get("insights", []) if accountability_output else [],
            "overall_health": accountability_output.get("overall_health", "steady") if accountability_output else "steady",

            "agents_used": [k for k, v in results.items() if v is not None],
        }

    def _save_insights(self, accountability_output):
        """Persist accountability insights to the database."""
        if not accountability_output:
            return
        today = date.today()
        for insight in accountability_output.get("insights", []):
            valid_days = insight.get("valid_days", 7)
            valid_until = (today + timedelta(days=valid_days)).isoformat()
            try:
                db.save_accountability_insight(
                    insight_type=insight.get("type", "pattern"),
                    title=insight.get("title", ""),
                    description=insight.get("description", ""),
                    related_goal_id=insight.get("related_goal_id"),
                    severity=insight.get("severity", "info"),
                    valid_until=valid_until,
                )
            except Exception as e:
                logger.warning(f"Failed to save insight: {e}")

    def _extract_email_actions(self, email_output):
        if not email_output:
            return []
        return [
            f"[{item['priority']}] {item['title']} (from: {item.get('source_sender', '?')})"
            for item in email_output.get("action_items", [])
        ]

    def _extract_learning_tasks(self, research_output):
        if not research_output:
            return []
        return [
            f"{task['title']} (~{task['estimated_minutes']}min, {task['task_type']})"
            for task in research_output.get("learning_tasks", [])
        ]

    def _extract_warnings(self, accountability_output):
        if not accountability_output:
            return []
        return [
            f"[{ins['severity']}] {ins['title']}: {ins['description']}"
            for ins in accountability_output.get("insights", [])
            if ins.get("severity") in ("warning", "critical")
        ]
