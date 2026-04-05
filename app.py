from flask import Flask, jsonify, request, render_template
from datetime import date

import database as db
import planner

app = Flask(__name__)
db.init_db()


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

if __name__ == "__main__":
    app.run(debug=True)
