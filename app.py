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
    # Try to parse ai_summary as JSON review
    import json
    ai_summary = reflection.get("ai_summary")
    if ai_summary:
        try:
            review_data = json.loads(ai_summary)
            if "reflection" in review_data:
                reflection["review"] = review_data
        except Exception:
            pass
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
