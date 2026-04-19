import json
import os
from flask import Flask, jsonify, request, render_template, redirect, session
from datetime import date
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import database as db
import planner

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))
db.init_db()

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "60 per hour"],
    storage_uri="memory://",
)

# Stricter limit applied to auth routes (5 attempts per 15 minutes)
_AUTH_LIMIT = "5 per 15 minutes"


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------

@app.route("/api/goals", methods=["GET"])
def list_goals():
    return jsonify(db.get_all_goals())


@app.route("/api/goals", methods=["POST"])
def create_goal():
    data = request.get_json(force=True)
    if not data.get("title") or not data.get("level"):
        return jsonify({"error": "title and level are required"}), 400
    goal = db.create_goal(
        title=data["title"],
        description=data.get("description"),
        level=data["level"],
        parent_id=data.get("parent_id"),
        deadline=data.get("deadline"),
    )
    return jsonify(goal), 201


@app.route("/api/goals/<int:goal_id>", methods=["PUT"])
def update_goal(goal_id):
    data = request.get_json(force=True)
    goal = db.update_goal(goal_id, **data)
    if goal is None:
        return jsonify({"error": "Goal not found"}), 404
    return jsonify(goal)


@app.route("/api/goals/<int:goal_id>", methods=["DELETE"])
def delete_goal(goal_id):
    db.delete_goal(goal_id)
    return jsonify({"ok": True})


@app.route("/api/goals/<int:goal_id>/status", methods=["PATCH"])
def update_goal_status(goal_id):
    data = request.get_json(force=True)
    status = data.get("status")
    if status not in ("active", "completed", "paused", "abandoned"):
        return jsonify({"error": "Invalid status"}), 400
    goal = db.update_goal(goal_id, status=status)
    if goal is None:
        return jsonify({"error": "Goal not found"}), 404
    return jsonify(goal)


# ---------------------------------------------------------------------------
# Daily Tasks
# ---------------------------------------------------------------------------

@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    date_str = request.args.get("date", date.today().isoformat())
    return jsonify(db.get_tasks_for_date(date_str))


@app.route("/api/tasks", methods=["POST"])
def create_task():
    data = request.get_json(force=True)
    if not data.get("title"):
        return jsonify({"error": "title is required"}), 400
    task = db.create_task(
        title=data["title"],
        description=data.get("description"),
        priority=data.get("priority", "medium"),
        goal_id=data.get("goal_id"),
        date_str=data.get("date", date.today().isoformat()),
        source="manual",
        estimated_minutes=data.get("estimated_minutes"),
    )
    return jsonify(task), 201


@app.route("/api/tasks/<int:task_id>/toggle", methods=["PATCH"])
def toggle_task(task_id):
    task = db.toggle_task(task_id)
    if task is None:
        return jsonify({"error": "Task not found"}), 404
    tasks_today = db.get_tasks_for_date(task["date"])
    done = sum(1 for t in tasks_today if t["completed"])
    db.upsert_reflection(task["date"], done, len(tasks_today))
    return jsonify(task)


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    db.delete_task(task_id)
    return jsonify({"ok": True})


@app.route("/api/tasks/<int:task_id>/review-rating", methods=["POST"])
def submit_review_rating(task_id):
    """Submit quality rating (1-5) for a completed review task."""
    task = db.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    if task.get("task_type") != "review":
        return jsonify({"error": "Not a review task"}), 400

    data = request.get_json(force=True) or {}
    quality = data.get("quality_rating")
    if quality not in (1, 2, 3, 4, 5):
        return jsonify({"error": "quality_rating must be 1-5"}), 400

    review_id = task.get("spaced_review_id")
    if review_id:
        db.complete_spaced_review(review_id, quality)

    # Update review compliance in user profile
    compliance = db.get_spaced_review_compliance(days=30)
    if compliance is not None:
        db.upsert_profile_entry("learning", "review_compliance", str(compliance))

    return jsonify({"ok": True, "quality_rating": quality, "spaced_review_id": review_id})


# ---------------------------------------------------------------------------
# Task Carry-Forward (Feature 1)
# ---------------------------------------------------------------------------

@app.route("/api/tasks/carry-forward", methods=["GET"])
def carry_forward_preview():
    """Return count of yesterday's incomplete tasks available to carry forward."""
    count = db.get_yesterday_incomplete_count()
    return jsonify({"count": count})


@app.route("/api/tasks/carry-forward", methods=["POST"])
def carry_forward():
    """Create today's copies of yesterday's incomplete tasks."""
    tasks = db.carry_forward_tasks()
    return jsonify(tasks)


# ---------------------------------------------------------------------------
# AI Planner
# ---------------------------------------------------------------------------

@app.route("/api/generate-plan", methods=["POST"])
def generate_plan():
    from config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        return jsonify({
            "error": "GEMINI_API_KEY is not configured. "
                     "Copy .env.example to .env and add your key from https://aistudio.google.com/apikey"
        }), 503

    result = planner.generate_daily_plan()
    if "error" in result:
        return jsonify(result), 502
    return jsonify(result)


# ---------------------------------------------------------------------------
# Daily Review (Feature 2)
# ---------------------------------------------------------------------------

@app.route("/api/review/daily", methods=["GET"])
def get_daily_review():
    date_str = request.args.get("date", date.today().isoformat())
    reflection = db.get_reflection_for_date(date_str)
    if not reflection:
        return jsonify(None)
    ai_summary = reflection.get("ai_summary")
    if ai_summary:
        try:
            review_data = json.loads(ai_summary)
            if "reflection" in review_data:
                reflection["review"] = review_data
        except Exception:
            pass
    # Attach escalated suggestions (level >= 2) for the UI
    all_suggestions = db.get_active_suggestions()
    reflection["escalations"] = [s for s in all_suggestions if s["escalation_level"] >= 2]
    return jsonify(reflection)


@app.route("/api/review/daily", methods=["POST"])
def create_daily_review():
    from config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY is not configured"}), 503

    data = request.get_json(force=True) or {}
    notes = data.get("notes")
    mood = data.get("mood")
    target_date = data.get("date", date.today().isoformat())

    result = planner.generate_daily_review(notes=notes, mood=mood, target_date=target_date)
    if "error" in result:
        return jsonify(result), 502
    return jsonify(result)


# ---------------------------------------------------------------------------
# Weekly Review (Feature 3)
# ---------------------------------------------------------------------------

@app.route("/api/review/escalation/<int:suggestion_id>/respond", methods=["POST"])
def escalation_respond(suggestion_id):
    """Handle user response to an escalated suggestion."""
    suggestion = db.get_suggestion(suggestion_id)
    if not suggestion:
        return jsonify({"error": "Suggestion not found"}), 404

    data = request.get_json(force=True) or {}
    action = data.get("action")
    if action not in ("still_important", "too_big", "pause", "drop"):
        return jsonify({"error": "action must be still_important, too_big, pause, or drop"}), 400

    related_goal_id = suggestion.get("related_goal_id")

    if action == "still_important":
        db.reset_suggestion_escalation(suggestion_id)
    elif action in ("too_big", "drop"):
        db.drop_suggestion(suggestion_id)
        if action == "drop" and related_goal_id:
            db.update_goal(related_goal_id, status="abandoned")
    elif action == "pause":
        db.drop_suggestion(suggestion_id)
        if related_goal_id:
            db.update_goal(related_goal_id, status="paused")

    return jsonify({"ok": True, "action": action, "related_goal_id": related_goal_id})


@app.route("/api/review/weekly", methods=["GET"])
def get_weekly_review():
    week_start = request.args.get("week_start")
    if not week_start:
        from datetime import timedelta
        today = date.today()
        week_start = (today - timedelta(days=today.weekday())).isoformat()
    review = db.get_weekly_review(week_start)
    if not review:
        return jsonify(None)
    # Parse ai_review JSON
    import json
    if review.get("ai_review"):
        try:
            review["review"] = json.loads(review["ai_review"])
        except Exception:
            pass
    return jsonify(review)


@app.route("/api/review/weekly", methods=["POST"])
def create_weekly_review():
    from config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY is not configured"}), 503

    data = request.get_json(force=True) or {}
    week_start = data.get("week_start")

    result = planner.generate_weekly_review(week_start=week_start)
    if "error" in result:
        return jsonify(result), 502
    return jsonify(result)


@app.route("/api/reviews/weekly/list", methods=["GET"])
def list_weekly_reviews():
    return jsonify(db.list_weekly_reviews())


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

@app.route("/api/progress", methods=["GET"])
def get_progress():
    days = int(request.args.get("days", 30))
    return jsonify(db.get_progress_data(days))


# ---------------------------------------------------------------------------
# Gmail OAuth
# ---------------------------------------------------------------------------

@app.route("/auth/gmail/status", methods=["GET"])
def gmail_status():
    import gmail_client
    return jsonify(gmail_client.is_connected())


@app.route("/auth/gmail/connect", methods=["GET"])
@limiter.limit(_AUTH_LIMIT)
def gmail_connect():
    from config import GOOGLE_CREDENTIALS_PATH
    if not GOOGLE_CREDENTIALS_PATH:
        return redirect("/?gmail=no_credentials")
    import gmail_client
    auth_url, state, _ = gmail_client.get_auth_url()
    if not auth_url:
        return redirect("/?gmail=no_credentials")
    return redirect(auth_url)


@app.route("/auth/gmail/callback", methods=["GET"])
@limiter.limit(_AUTH_LIMIT)
def gmail_callback():
    code = request.args.get("code")
    error = request.args.get("error")
    if error or not code:
        return redirect("/?gmail=denied")
    try:
        import gmail_client
        gmail_client.handle_callback(code)
        return redirect("/?gmail=connected")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return redirect(f"/?gmail=error")


@app.route("/auth/gmail/disconnect", methods=["POST"])
@limiter.limit(_AUTH_LIMIT)
def gmail_disconnect():
    import gmail_client
    gmail_client.disconnect()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Email API
# ---------------------------------------------------------------------------

@app.route("/api/email/scan", methods=["POST"])
def email_scan():
    from config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY is not configured"}), 503

    import gmail_client, email_processor
    status = gmail_client.is_connected()
    if not status["connected"]:
        return jsonify({"error": "Gmail not connected", "code": "NOT_CONNECTED"}), 400

    try:
        emails = gmail_client.fetch_recent_emails(hours=24, max_results=50)
    except Exception as e:
        err_str = str(e)
        if "403" in err_str:
            return jsonify({"error": "Insufficient Gmail permissions. Please reconnect.", "code": "FORBIDDEN"}), 403
        if "429" in err_str:
            return jsonify({"error": "Too many requests, try again in a minute.", "code": "RATE_LIMITED"}), 429
        return jsonify({"error": f"Failed to fetch emails: {err_str}"}), 502

    if emails is None:
        return jsonify({"error": "Gmail not connected", "code": "NOT_CONNECTED"}), 400

    try:
        result = email_processor.process_emails(emails)
    except Exception as e:
        # Still save raw emails so user can retry without re-fetching
        today = date.today().isoformat()
        digest_id = db.upsert_email_digest(
            today, len(emails), None, json.dumps(emails)
        )
        return jsonify({"error": f"Could not process emails — try again: {str(e)}"}), 502

    today = date.today().isoformat()
    digest_id = db.upsert_email_digest(
        today,
        len(emails),
        result.get("summary"),
        json.dumps(emails),
    )
    db.save_email_action_items(digest_id, result.get("action_items", []))

    digest = db.get_email_digest_for_date(today)
    digest["categories"] = result.get("categories", {})
    return jsonify(digest)


@app.route("/api/email/digest", methods=["GET"])
def email_digest():
    date_str = request.args.get("date", date.today().isoformat())
    digest = db.get_email_digest_for_date(date_str)
    if not digest:
        return jsonify(None)
    return jsonify(digest)


@app.route("/api/email/action/<int:item_id>/accept", methods=["PATCH"])
def email_action_accept(item_id):
    item = db.get_email_action_item(item_id)
    if not item:
        return jsonify({"error": "Action item not found"}), 404

    task = db.create_task(
        title=item["title"],
        description=item.get("description"),
        priority=item.get("priority", "medium"),
        goal_id=None,
        date_str=date.today().isoformat(),
        source="email",
    )
    db.update_email_action_item(item_id, status="accepted", task_id=task["id"])
    return jsonify(task), 201


@app.route("/api/email/action/<int:item_id>/dismiss", methods=["PATCH"])
def email_action_dismiss(item_id):
    item = db.get_email_action_item(item_id)
    if not item:
        return jsonify({"error": "Action item not found"}), 404
    db.update_email_action_item(item_id, status="dismissed")
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Telegram Config
# ---------------------------------------------------------------------------

@app.route("/api/config/telegram", methods=["GET"])
def telegram_config_get():
    config = db.get_bot_config("telegram")
    if not config:
        return jsonify({"connected": False, "chat_id": None, "settings": {}})
    settings = {}
    try:
        settings = json.loads(config.get("settings_json") or "{}")
    except Exception:
        pass
    return jsonify({
        "connected": bool(config.get("chat_id")),
        "chat_id": config.get("chat_id"),
        "enabled": bool(config.get("enabled")),
        "settings": settings,
    })


@app.route("/api/config/telegram/settings", methods=["PUT"])
def telegram_config_update():
    data = request.get_json(force=True) or {}
    config = db.get_bot_config("telegram")
    if not config:
        return jsonify({"error": "Telegram not connected yet"}), 404

    try:
        existing = json.loads(config.get("settings_json") or "{}")
    except Exception:
        existing = {}

    allowed_keys = {
        "morning_plan_time", "evening_review_time",
        "send_morning_plan", "send_evening_reminder", "send_email_alerts", "timezone",
    }
    for k in allowed_keys:
        if k in data:
            existing[k] = data[k]

    db.update_bot_config("telegram", settings_json=json.dumps(existing))

    # Reschedule if times/timezone changed
    if any(k in data for k in ("morning_plan_time", "evening_review_time", "timezone")):
        import scheduler as sched
        try:
            sched.update_schedule_times(
                existing.get("morning_plan_time", "07:00"),
                existing.get("evening_review_time", "21:00"),
                existing.get("timezone", "UTC"),
            )
        except Exception:
            pass

    return jsonify(existing)


# ---------------------------------------------------------------------------
# Scheduler Status
# ---------------------------------------------------------------------------

@app.route("/api/scheduler/status", methods=["GET"])
def scheduler_status():
    import scheduler as sched
    return jsonify(sched.get_status())


@app.route("/api/scheduler/trigger/<job_id>", methods=["POST"])
def scheduler_trigger(job_id):
    import scheduler as sched
    ok = sched.trigger_job(job_id)
    if not ok:
        return jsonify({"error": f"Unknown or failed job: {job_id}"}), 400
    return jsonify({"triggered": job_id})


# ---------------------------------------------------------------------------
# Learning Resources
# ---------------------------------------------------------------------------

@app.route("/api/resources", methods=["GET"])
def list_resources():
    goal_id = request.args.get("goal_id", type=int)
    return jsonify(db.get_learning_resources(goal_id=goal_id))


@app.route("/api/resources", methods=["POST"])
def create_resource():
    data = request.get_json(force=True) or {}
    if not data.get("title"):
        return jsonify({"error": "title is required"}), 400
    resource = db.create_learning_resource(
        goal_id=data.get("goal_id"),
        type_=data.get("type", "book"),
        title=data["title"],
        author=data.get("author"),
        url=data.get("url"),
        total_units=data.get("total_units"),
        unit_label=data.get("unit_label", "chapter"),
        notes=data.get("notes"),
    )
    return jsonify(resource), 201


@app.route("/api/resources/<int:resource_id>", methods=["PUT"])
def update_resource(resource_id):
    data = request.get_json(force=True) or {}
    resource = db.get_learning_resource(resource_id)
    if not resource:
        return jsonify({"error": "Not found"}), 404
    # Map "type" → "type_" for DB layer
    if "type" in data:
        data["type"] = data["type"]  # kept as-is; db function uses keyword arg
    allowed = {"goal_id", "type", "title", "author", "url", "total_units",
               "completed_units", "unit_label", "status", "notes"}
    updates = {k: v for k, v in data.items() if k in allowed}
    return jsonify(db.update_learning_resource(resource_id, **updates))


@app.route("/api/resources/<int:resource_id>/progress", methods=["PATCH"])
def update_resource_progress(resource_id):
    data = request.get_json(force=True) or {}
    completed_units = data.get("completed_units")
    if completed_units is None:
        return jsonify({"error": "completed_units is required"}), 400
    resource = db.get_learning_resource(resource_id)
    if not resource:
        return jsonify({"error": "Not found"}), 404
    updated = db.update_learning_resource(resource_id, completed_units=completed_units)
    return jsonify(updated)


@app.route("/api/resources/<int:resource_id>", methods=["DELETE"])
def delete_resource(resource_id):
    if not db.get_learning_resource(resource_id):
        return jsonify({"error": "Not found"}), 404
    db.delete_learning_resource(resource_id)
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Accountability Insights
# ---------------------------------------------------------------------------

@app.route("/api/insights", methods=["GET"])
def list_insights():
    insights = db.get_active_insights(limit=20)
    return jsonify(insights)


@app.route("/api/insights/<int:insight_id>/acknowledge", methods=["PATCH"])
def acknowledge_insight(insight_id):
    insight = db.get_accountability_insight(insight_id)
    if not insight:
        return jsonify({"error": "Not found"}), 404
    return jsonify(db.acknowledge_insight(insight_id))


# ---------------------------------------------------------------------------
# Agent Logs & Status
# ---------------------------------------------------------------------------

@app.route("/api/agents/logs", methods=["GET"])
def agent_logs():
    agent = request.args.get("agent")
    limit = request.args.get("limit", 20, type=int)
    return jsonify(db.get_agent_logs(agent_name=agent, limit=limit))


@app.route("/api/agents/status", methods=["GET"])
def agent_status():
    known = ["planner", "email", "research", "accountability"]
    by_name = {row["agent_name"]: row for row in db.get_agents_status()}
    result = []
    for name in known:
        row = by_name.get(name)
        result.append({
            "name": name,
            "available": True,
            "last_run": row["last_run"] if row else None,
            "last_status": "success" if (row and row.get("last_status")) else ("failed" if row else "never"),
        })
    return jsonify({"agents": result})


# ---------------------------------------------------------------------------
# Streaming plan generation (SSE)
# ---------------------------------------------------------------------------

@app.route("/api/generate-plan/stream", methods=["POST"])
def generate_plan_stream():
    from config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY is not configured"}), 503

    from flask import Response, stream_with_context
    from agents.orchestrator import Orchestrator, _is_gmail_connected, _has_learning_goals
    from agents.orchestrator import _accountability_ran_recently
    import json as _json

    def generate():
        orchestrator = Orchestrator()
        results = {}

        # Accountability
        yield _json.dumps({"agent": "accountability", "status": "running"}) + "\n"
        try:
            if _accountability_ran_recently():
                cached_log = db.get_latest_agent_log("accountability")
                if cached_log and cached_log.get("parsed_output"):
                    results["accountability"] = _json.loads(cached_log["parsed_output"])
                else:
                    results["accountability"] = None
            else:
                results["accountability"] = orchestrator.accountability_agent.run(
                    trigger_type="orchestrated"
                )
                orchestrator._save_insights(results["accountability"])
            yield _json.dumps({"agent": "accountability", "status": "done",
                               "data": results["accountability"]}) + "\n"
        except Exception as e:
            results["accountability"] = None
            yield _json.dumps({"agent": "accountability", "status": "error",
                               "error": str(e)}) + "\n"

        # Email
        if _is_gmail_connected():
            yield _json.dumps({"agent": "email", "status": "running"}) + "\n"
            try:
                import gmail_client
                emails = gmail_client.fetch_recent_emails(hours=24, max_results=50) or []
                results["email"] = orchestrator.email_agent.run(
                    extra_input={"emails": emails}, trigger_type="orchestrated"
                )
                yield _json.dumps({"agent": "email", "status": "done",
                                   "data": results["email"]}) + "\n"
            except Exception as e:
                results["email"] = None
                yield _json.dumps({"agent": "email", "status": "error",
                                   "error": str(e)}) + "\n"
        else:
            results["email"] = None

        # Research
        if _has_learning_goals():
            yield _json.dumps({"agent": "research", "status": "running"}) + "\n"
            try:
                results["research"] = orchestrator.research_agent.run(
                    trigger_type="orchestrated"
                )
                yield _json.dumps({"agent": "research", "status": "done",
                                   "data": results["research"]}) + "\n"
            except Exception as e:
                results["research"] = None
                yield _json.dumps({"agent": "research", "status": "error",
                                   "error": str(e)}) + "\n"
        else:
            results["research"] = None

        # Planner
        yield _json.dumps({"agent": "planner", "status": "running"}) + "\n"
        try:
            agent_inputs = {
                "email_actions": orchestrator._extract_email_actions(results.get("email")),
                "learning_tasks": orchestrator._extract_learning_tasks(results.get("research")),
                "accountability_warnings": orchestrator._extract_warnings(results.get("accountability")),
            }
            results["planner"] = orchestrator.planner.run(
                extra_input=agent_inputs, trigger_type="orchestrated"
            )

            # Persist tasks
            today_str = date.today().isoformat()
            inserted = []
            for t in results["planner"].get("tasks", []):
                task = db.create_task(
                    title=t.get("title", "Untitled"),
                    description=t.get("description"),
                    priority=t.get("priority", "medium"),
                    goal_id=t.get("goal_id"),
                    date_str=today_str,
                    source="ai",
                    estimated_minutes=t.get("estimated_minutes"),
                    blueprint_unit_id=t.get("blueprint_unit_id"),
                    energy_level=t.get("energy_level"),
                    suggested_slot=t.get("suggested_slot"),
                    task_type=t.get("task_type", "normal"),
                    spaced_review_id=t.get("spaced_review_id"),
                )
                inserted.append(task)
            results["planner"]["tasks"] = inserted

            all_today = db.get_tasks_for_date(today_str)
            done = sum(1 for t in all_today if t["completed"])
            db.upsert_reflection(today_str, done, len(all_today),
                                 ai_summary=results["planner"].get("daily_insight"))

            final = orchestrator._merge_outputs(results)
            final["tasks"] = inserted
            yield _json.dumps({"agent": "planner", "status": "done", "data": final}) + "\n"
        except Exception as e:
            yield _json.dumps({"agent": "planner", "status": "error", "error": str(e)}) + "\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/plain",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"},
    )


# ---------------------------------------------------------------------------
# Phase 6 — Goal Blueprints
# ---------------------------------------------------------------------------

@app.route("/api/goals/<int:goal_id>/research", methods=["POST"])
def research_goal_blueprint(goal_id):
    """Research a goal and return a proposed blueprint (not saved to DB)."""
    import goal_researcher

    goal = db.get_goal(goal_id)
    if not goal:
        return jsonify({"error": "Goal not found"}), 404

    data = request.get_json(force=True)
    goal_type = data.get("type")
    details = data.get("details", {})

    if goal_type not in ("learning", "career", "habit"):
        return jsonify({"error": "type must be learning, career, or habit"}), 400

    try:
        result = goal_researcher.research_and_build(
            goal_type=goal_type,
            goal_id=goal_id,
            details=details,
            deadline=goal.get("deadline"),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "manual_mode": True}), 422


@app.route("/api/goals/<int:goal_id>/blueprint", methods=["POST"])
def save_blueprint(goal_id):
    """Save a confirmed blueprint (from the wizard) and run the scheduler."""
    import blueprint_scheduler
    data = request.get_json(force=True)
    if not data.get("blueprint_type") or not data.get("title"):
        return jsonify({"error": "blueprint_type and title are required"}), 400

    # Delete existing blueprint for this goal (wizard re-confirms)
    existing = db.get_blueprint_by_goal(goal_id)
    if existing:
        conn = db.get_connection()
        with conn:
            conn.execute("DELETE FROM goal_blueprints WHERE goal_id = ?", (goal_id,))
        conn.close()

    units_data = data.get("units", [])
    milestones_data = data.get("milestones", [])

    bp = db.create_blueprint(
        goal_id=goal_id,
        blueprint_type=data["blueprint_type"],
        title=data["title"],
        source_info=data.get("source_info"),
        total_units=len(units_data) or data.get("total_units", 0),
        unit_label=data.get("unit_label", "unit"),
        schedule_strategy=data.get("schedule_strategy", "even"),
        difficulty_curve=data.get("difficulty_curve"),
        estimated_pace_minutes=data.get("estimated_pace_minutes"),
    )

    # Create milestones and build index for unit linkage
    ms_id_map: dict[int, int] = {}  # milestone list index → db id
    for idx, ms in enumerate(milestones_data):
        ms_row = db.create_milestone(
            blueprint_id=bp["id"],
            title=ms["title"],
            description=ms.get("description"),
            target_date=ms.get("target_date"),
            sort_order=ms.get("sort_order", idx),
        )
        ms_id_map[idx] = ms_row["id"]

    # Create units; resolve depends_on by unit_number→id mapping
    unit_num_to_id: dict[int, int] = {}
    for u in sorted(units_data, key=lambda x: x.get("unit_number", 0)):
        ms_idx = u.get("milestone_index")
        ms_id = ms_id_map.get(ms_idx) if ms_idx is not None else None
        dep_num = u.get("depends_on_unit_number")
        dep_id = unit_num_to_id.get(dep_num) if dep_num is not None else None
        unit_row = db.create_blueprint_unit(
            blueprint_id=bp["id"],
            unit_number=u["unit_number"],
            title=u["title"],
            description=u.get("description"),
            milestone_id=ms_id,
            estimated_minutes=u.get("estimated_minutes"),
            difficulty=u.get("difficulty", 1.0),
            depends_on=dep_id,
            metadata=u.get("metadata"),
        )
        unit_num_to_id[u["unit_number"]] = unit_row["id"]

    # Create habit config if provided
    if data.get("habit_config") and data["blueprint_type"] == "habit":
        hc = data["habit_config"]
        db.create_habit_config(
            blueprint_id=bp["id"],
            frequency=hc["frequency"],
            progression_type=hc.get("progression_type", "constant"),
            base_quantity=hc.get("base_quantity"),
            current_quantity=hc.get("current_quantity"),
            target_quantity=hc.get("target_quantity"),
            quantity_unit=hc.get("quantity_unit"),
            increment_amount=hc.get("increment_amount"),
            increment_frequency=hc.get("increment_frequency", "weekly"),
            custom_days=hc.get("custom_days"),
        )

    # Run scheduling algorithm
    blueprint_scheduler.schedule_blueprint(bp["id"])

    return jsonify(db.get_blueprint(bp["id"])), 201


@app.route("/api/goals/<int:goal_id>/blueprint", methods=["GET"])
def get_goal_blueprint(goal_id):
    """Return a goal's blueprint with milestones, units, schedule status, and type-specific data."""
    bp = db.get_blueprint_by_goal(goal_id)
    if not bp:
        return jsonify({"error": "No blueprint for this goal"}), 404
    bp["schedule_status"] = db.get_blueprint_schedule_status(bp["id"])
    bp["units"] = db.get_blueprint_units(bp["id"])
    if bp.get("blueprint_type") == "habit":
        bp["habit_config"] = db.get_habit_config(bp["id"])
        bp["habit_streak"] = db.get_habit_streak(bp["id"])
    elif bp.get("blueprint_type") == "career":
        bp["pipeline"] = db.get_pipeline_entries(bp["id"])
        bp["pipeline_stats"] = db.get_pipeline_stats(bp["id"])
    return jsonify(bp)


@app.route("/api/blueprints/<int:blueprint_id>", methods=["GET"])
def get_blueprint(blueprint_id):
    bp = db.get_blueprint(blueprint_id)
    if not bp:
        return jsonify({"error": "Blueprint not found"}), 404
    bp["schedule_status"] = db.get_blueprint_schedule_status(blueprint_id)
    return jsonify(bp)


@app.route("/api/blueprints/<int:blueprint_id>", methods=["PUT"])
def update_blueprint(blueprint_id):
    data = request.get_json(force=True)
    bp = db.update_blueprint(blueprint_id, **data)
    if not bp:
        return jsonify({"error": "Blueprint not found"}), 404
    return jsonify(bp)


@app.route("/api/blueprints/<int:blueprint_id>/reschedule", methods=["POST"])
def reschedule_blueprint(blueprint_id):
    import blueprint_scheduler
    ok = blueprint_scheduler.reschedule_blueprint(blueprint_id)
    if not ok:
        return jsonify({"error": "Blueprint not found"}), 404
    bp = db.get_blueprint(blueprint_id)
    bp["schedule_status"] = db.get_blueprint_schedule_status(blueprint_id)
    return jsonify(bp)


@app.route("/api/blueprints/<int:blueprint_id>/units", methods=["GET"])
def list_blueprint_units(blueprint_id):
    status_filter = request.args.getlist("status") or None
    units = db.get_blueprint_units(blueprint_id, status_filter=status_filter)
    return jsonify(units)


# ---------------------------------------------------------------------------
# Phase 6 — Blueprint Units
# ---------------------------------------------------------------------------

@app.route("/api/units/<int:unit_id>/complete", methods=["PATCH"])
def complete_unit(unit_id):
    data = request.get_json(force=True) or {}
    actual_minutes = data.get("actual_minutes")
    unit = db.complete_blueprint_unit(unit_id, actual_minutes)
    if not unit:
        return jsonify({"error": "Unit not found"}), 404
    return jsonify(unit)


@app.route("/api/units/<int:unit_id>/skip", methods=["PATCH"])
def skip_unit(unit_id):
    unit = db.skip_blueprint_unit(unit_id)
    if not unit:
        return jsonify({"error": "Unit not found"}), 404
    return jsonify(unit)


# ---------------------------------------------------------------------------
# Phase 6 — Habits
# ---------------------------------------------------------------------------

@app.route("/api/habits", methods=["GET"])
def list_habits():
    return jsonify(db.get_all_habits())


@app.route("/api/habits/<int:blueprint_id>/log", methods=["PATCH"])
def log_habit_today(blueprint_id):
    """Log today's habit as done. Marks the scheduled unit complete and returns streak."""
    import json as _json
    data = request.get_json(force=True) or {}
    actual_quantity = data.get("actual_quantity")
    actual_minutes = data.get("actual_minutes")

    unit = db.get_today_habit_unit(blueprint_id)
    if not unit:
        return jsonify({"error": "No pending unit found for today"}), 404

    if actual_quantity is not None:
        try:
            meta = _json.loads(unit["metadata"]) if unit.get("metadata") else {}
        except Exception:
            meta = {}
        meta["actual_quantity"] = actual_quantity
        conn = db.get_connection()
        with conn:
            conn.execute("UPDATE blueprint_units SET metadata=? WHERE id=?",
                         (_json.dumps(meta), unit["id"]))
        conn.close()

    completed = db.complete_blueprint_unit(unit["id"], actual_minutes=actual_minutes)
    db.check_habit_progression()
    streak = db.get_habit_streak(blueprint_id)
    return jsonify({"unit": completed, "streak": streak})


@app.route("/api/habits/<int:habit_config_id>/increment", methods=["POST"])
def increment_habit(habit_config_id):
    """Manually trigger a quantity increment for a progressive habit."""
    hc = db.get_habit_config_by_id(habit_config_id)
    if not hc:
        return jsonify({"error": "Habit config not found"}), 404
    if hc["target_quantity"] is None:
        return jsonify({"error": "Habit is not progressive"}), 400
    inc = hc.get("increment_amount") or 0
    new_qty = min((hc["current_quantity"] or 0) + inc, hc["target_quantity"])
    updated = db.update_habit_quantity(habit_config_id, new_qty)
    return jsonify(updated)


# ---------------------------------------------------------------------------
# Phase 6 — Career Pipeline
# ---------------------------------------------------------------------------

@app.route("/api/career/pipeline", methods=["GET"])
def list_pipeline():
    blueprint_id = request.args.get("blueprint_id", type=int)
    if not blueprint_id:
        return jsonify({"error": "blueprint_id query param required"}), 400
    return jsonify(db.get_pipeline_entries(blueprint_id))


@app.route("/api/career/pipeline", methods=["POST"])
def create_pipeline_entry():
    data = request.get_json(force=True)
    if not data.get("blueprint_id") or not data.get("entry_type") or not data.get("title"):
        return jsonify({"error": "blueprint_id, entry_type, and title are required"}), 400
    entry = db.create_pipeline_entry(
        blueprint_id=data["blueprint_id"],
        entry_type=data["entry_type"],
        title=data["title"],
        company=data.get("company"),
        status=data.get("status"),
        url=data.get("url"),
        notes=data.get("notes"),
        deadline=data.get("deadline"),
        follow_up_date=data.get("follow_up_date"),
    )
    return jsonify(entry), 201


@app.route("/api/career/pipeline/<int:entry_id>", methods=["PUT"])
def update_pipeline_entry(entry_id):
    data = request.get_json(force=True)
    entry = db.update_pipeline_entry(entry_id, **data)
    if not entry:
        return jsonify({"error": "Entry not found"}), 404
    return jsonify(entry)


@app.route("/api/career/pipeline/stats", methods=["GET"])
def pipeline_stats():
    blueprint_id = request.args.get("blueprint_id", type=int)
    if not blueprint_id:
        return jsonify({"error": "blueprint_id query param required"}), 400
    return jsonify(db.get_pipeline_stats(blueprint_id))


# ---------------------------------------------------------------------------
# Phase 7 — Energy Curve
# ---------------------------------------------------------------------------

@app.route("/api/energy-curve", methods=["GET"])
def get_energy_curve():
    return jsonify(db.get_energy_curve())


@app.route("/api/energy-curve", methods=["PUT"])
def save_energy_curve():
    data = request.get_json(force=True) or {}
    valid_energy = {"low", "medium", "high"}
    for i in range(1, 6):
        key = f"slot_{i}_energy"
        if key in data and data[key] not in valid_energy:
            return jsonify({"error": f"Invalid value for {key}: must be low, medium, or high"}), 400
    curve = db.upsert_energy_curve(
        user_defined=True,
        slot_1_energy=data.get("slot_1_energy", "medium"),
        slot_2_energy=data.get("slot_2_energy", "high"),
        slot_3_energy=data.get("slot_3_energy", "low"),
        slot_4_energy=data.get("slot_4_energy", "medium"),
        slot_5_energy=data.get("slot_5_energy", "medium"),
    )
    return jsonify(curve)


@app.route("/api/energy-curve/detect", methods=["POST"])
def detect_energy_curve():
    detected = db.detect_energy_curve_from_history()
    if not detected:
        return jsonify({
            "error": "Not enough data — need at least 10 completed tasks with timestamps in the last 30 days"
        }), 422
    curve = db.upsert_energy_curve(
        user_defined=False,
        slot_1_energy=detected.get(1, "medium"),
        slot_2_energy=detected.get(2, "high"),
        slot_3_energy=detected.get(3, "low"),
        slot_4_energy=detected.get(4, "medium"),
        slot_5_energy=detected.get(5, "medium"),
    )
    return jsonify(curve)


# ---------------------------------------------------------------------------
# Rate-limit error handler
# ---------------------------------------------------------------------------

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "Too many requests", "detail": str(e.description)}), 429


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os, threading

    # app.debug is still False here (set later by app.run), so use a local constant.
    # In debug mode the watchdog reloader forks: parent has no WERKZEUG_RUN_MAIN,
    # child has WERKZEUG_RUN_MAIN='true'. Start bot/scheduler only in the child
    # to avoid two instances polling the same token simultaneously.
    DEBUG = True
    _is_main_process = not DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true"

    from config import TELEGRAM_BOT_TOKEN
    if TELEGRAM_BOT_TOKEN and _is_main_process:
        from telegram_bot import start_bot
        bot_thread = threading.Thread(target=start_bot, daemon=True, name="telegram-bot")
        bot_thread.start()

    import scheduler as sched
    sched.init_scheduler(app)

    app.run(debug=DEBUG)
