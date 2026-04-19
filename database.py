import sqlite3
import json
from datetime import date, datetime, timedelta
from config import DATABASE_PATH


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                level TEXT NOT NULL CHECK(level IN ('yearly', 'monthly', 'weekly')),
                parent_id INTEGER REFERENCES goals(id) ON DELETE CASCADE,
                status TEXT DEFAULT 'active' CHECK(status IN ('active', 'completed', 'paused', 'abandoned')),
                deadline DATE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS daily_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL DEFAULT (date('now')),
                title TEXT NOT NULL,
                description TEXT,
                priority TEXT CHECK(priority IN ('high', 'medium', 'low')),
                goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
                completed BOOLEAN DEFAULT 0,
                completed_at DATETIME,
                source TEXT DEFAULT 'ai' CHECK(source IN ('ai', 'manual')),
                estimated_minutes INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS daily_reflections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE UNIQUE NOT NULL DEFAULT (date('now')),
                tasks_completed INTEGER DEFAULT 0,
                tasks_total INTEGER DEFAULT 0,
                ai_summary TEXT,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS weekly_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start DATE NOT NULL,
                week_end DATE NOT NULL,
                total_tasks INTEGER,
                completed_tasks INTEGER,
                completion_rate REAL,
                goals_progressed TEXT,
                goals_neglected TEXT,
                ai_review TEXT,
                focus_areas TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(week_start)
            );

            CREATE TABLE IF NOT EXISTS oauth_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT UNIQUE NOT NULL,
                token_json TEXT NOT NULL,
                email TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS email_digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL DEFAULT (date('now')),
                emails_scanned INTEGER DEFAULT 0,
                ai_summary TEXT,
                raw_emails_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date)
            );

            CREATE TABLE IF NOT EXISTS email_action_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                digest_id INTEGER REFERENCES email_digests(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT,
                priority TEXT,
                source_subject TEXT,
                source_sender TEXT,
                status TEXT DEFAULT 'pending',
                task_id INTEGER REFERENCES daily_tasks(id) ON DELETE SET NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bot_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT UNIQUE NOT NULL,
                chat_id TEXT,
                enabled BOOLEAN DEFAULT 1,
                settings_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                input_summary TEXT,
                raw_prompt TEXT,
                raw_response TEXT,
                parsed_output TEXT,
                tokens_used INTEGER,
                duration_ms INTEGER,
                success BOOLEAN DEFAULT 1,
                error_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS learning_resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id INTEGER REFERENCES goals(id) ON DELETE CASCADE,
                type TEXT CHECK(type IN ('book', 'course', 'tutorial', 'article', 'video', 'other')),
                title TEXT NOT NULL,
                author TEXT,
                url TEXT,
                total_units INTEGER,
                completed_units INTEGER DEFAULT 0,
                unit_label TEXT DEFAULT 'chapter',
                status TEXT DEFAULT 'in_progress' CHECK(status IN ('not_started', 'in_progress', 'completed', 'dropped')),
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS accountability_insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                insight_type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                related_goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
                severity TEXT CHECK(severity IN ('info', 'warning', 'critical')),
                acknowledged BOOLEAN DEFAULT 0,
                valid_until DATE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS goal_blueprints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id INTEGER UNIQUE REFERENCES goals(id) ON DELETE CASCADE,
                blueprint_type TEXT NOT NULL CHECK(blueprint_type IN ('learning', 'career', 'habit')),
                title TEXT NOT NULL,
                source_info TEXT,
                total_units INTEGER,
                completed_units INTEGER DEFAULT 0,
                unit_label TEXT DEFAULT 'unit',
                schedule_strategy TEXT DEFAULT 'even' CHECK(schedule_strategy IN ('even', 'front_loaded', 'back_loaded', 'adaptive')),
                difficulty_curve TEXT,
                estimated_pace_minutes REAL,
                actual_pace_minutes REAL,
                pace_samples INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active' CHECK(status IN ('draft', 'active', 'completed', 'paused')),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS blueprint_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blueprint_id INTEGER REFERENCES goal_blueprints(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT,
                target_date DATE,
                completed BOOLEAN DEFAULT 0,
                completed_at DATETIME,
                sort_order INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS blueprint_units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blueprint_id INTEGER REFERENCES goal_blueprints(id) ON DELETE CASCADE,
                milestone_id INTEGER REFERENCES blueprint_milestones(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                description TEXT,
                unit_number INTEGER NOT NULL,
                estimated_minutes INTEGER,
                actual_minutes INTEGER,
                difficulty REAL DEFAULT 1.0,
                scheduled_date DATE,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed', 'skipped')),
                completed_at DATETIME,
                depends_on INTEGER REFERENCES blueprint_units(id),
                metadata TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS habit_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blueprint_id INTEGER UNIQUE REFERENCES goal_blueprints(id) ON DELETE CASCADE,
                frequency TEXT NOT NULL CHECK(frequency IN ('daily', 'weekdays', 'weekends', 'custom')),
                custom_days TEXT,
                progression_type TEXT DEFAULT 'constant' CHECK(progression_type IN ('constant', 'progressive')),
                base_quantity REAL,
                current_quantity REAL,
                target_quantity REAL,
                quantity_unit TEXT,
                increment_amount REAL,
                increment_frequency TEXT DEFAULT 'weekly' CHECK(increment_frequency IN ('daily', 'weekly', 'biweekly', 'monthly')),
                last_increment_date DATE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS career_pipeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blueprint_id INTEGER REFERENCES goal_blueprints(id) ON DELETE CASCADE,
                entry_type TEXT NOT NULL CHECK(entry_type IN ('application', 'interview', 'portfolio_piece', 'networking', 'skill_gap')),
                title TEXT NOT NULL,
                company TEXT,
                status TEXT,
                url TEXT,
                notes TEXT,
                deadline DATE,
                follow_up_date DATE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                data_points INTEGER DEFAULT 1,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, key)
            );

            CREATE TABLE IF NOT EXISTS reflection_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                suggestion TEXT NOT NULL,
                suggestion_category TEXT,
                related_goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
                times_given INTEGER DEFAULT 1,
                times_followed INTEGER DEFAULT 0,
                first_given DATE NOT NULL,
                last_given DATE NOT NULL,
                follow_through_rate REAL DEFAULT 0.0,
                status TEXT DEFAULT 'active' CHECK(status IN ('active', 'resolved', 'escalated', 'dropped')),
                escalation_level INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS energy_curve (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_defined BOOLEAN DEFAULT 0,
                slot_1_label TEXT DEFAULT 'Early Morning',
                slot_1_energy TEXT DEFAULT 'medium',
                slot_2_label TEXT DEFAULT 'Morning',
                slot_2_energy TEXT DEFAULT 'high',
                slot_3_label TEXT DEFAULT 'Early Afternoon',
                slot_3_energy TEXT DEFAULT 'low',
                slot_4_label TEXT DEFAULT 'Late Afternoon',
                slot_4_energy TEXT DEFAULT 'medium',
                slot_5_label TEXT DEFAULT 'Evening',
                slot_5_energy TEXT DEFAULT 'medium',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS spaced_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blueprint_unit_id INTEGER REFERENCES blueprint_units(id) ON DELETE CASCADE,
                review_number INTEGER DEFAULT 1,
                scheduled_date DATE NOT NULL,
                completed BOOLEAN DEFAULT 0,
                completed_at DATETIME,
                quality_rating INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)

    # Schema migrations — safe to re-run
    migrations = [
        "ALTER TABLE daily_tasks ADD COLUMN carried_from DATE DEFAULT NULL",
        "ALTER TABLE daily_reflections ADD COLUMN mood TEXT CHECK(mood IN ('great', 'good', 'okay', 'rough', 'bad')) DEFAULT NULL",
        "ALTER TABLE daily_tasks ADD COLUMN blueprint_unit_id INTEGER REFERENCES blueprint_units(id) ON DELETE SET NULL",
        "ALTER TABLE daily_tasks ADD COLUMN energy_level TEXT DEFAULT NULL",
        "ALTER TABLE daily_tasks ADD COLUMN suggested_slot TEXT DEFAULT NULL",
        "ALTER TABLE daily_tasks ADD COLUMN task_type TEXT DEFAULT 'normal'",
        "ALTER TABLE daily_tasks ADD COLUMN spaced_review_id INTEGER REFERENCES spaced_reviews(id) ON DELETE SET NULL",
    ]
    for sql in migrations:
        try:
            with conn:
                conn.execute(sql)
        except Exception:
            pass

    # Clean up email digests older than 7 days
    with conn:
        conn.execute(
            """DELETE FROM email_action_items WHERE digest_id IN (
                SELECT id FROM email_digests WHERE date < date('now', '-7 days')
            )"""
        )
        conn.execute("DELETE FROM email_digests WHERE date < date('now', '-7 days')")

    # Clean up agent_logs older than 30 days
    with conn:
        conn.execute("DELETE FROM agent_logs WHERE created_at < datetime('now', '-30 days')")

    conn.close()


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------

def create_goal(title, description=None, level="yearly", parent_id=None, deadline=None):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO goals (title, description, level, parent_id, deadline)
               VALUES (?, ?, ?, ?, ?)""",
            (title, description, level, parent_id, deadline),
        )
        goal_id = cur.lastrowid
    conn.close()
    return get_goal(goal_id)


def get_goal(goal_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_goals():
    """Return goals as a nested tree: yearly -> monthly -> weekly."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM goals ORDER BY created_at ASC").fetchall()
    conn.close()

    goals = [dict(r) for r in rows]
    by_id = {g["id"]: g for g in goals}
    for g in goals:
        g["children"] = []

    roots = []
    for g in goals:
        if g["parent_id"] and g["parent_id"] in by_id:
            by_id[g["parent_id"]]["children"].append(g)
        else:
            roots.append(g)
    return roots


def get_active_goals_flat():
    """Return all active goals as a flat list (for prompt building)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM goals WHERE status = 'active' ORDER BY level, created_at"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_goal(goal_id, **fields):
    allowed = {"title", "description", "level", "parent_id", "status", "deadline"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_goal(goal_id)
    updates["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [goal_id]
    conn = get_connection()
    with conn:
        conn.execute(f"UPDATE goals SET {set_clause} WHERE id = ?", values)
    conn.close()
    return get_goal(goal_id)


def delete_goal(goal_id):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    conn.close()


# ---------------------------------------------------------------------------
# Daily Tasks
# ---------------------------------------------------------------------------

def create_task(title, description=None, priority="medium", goal_id=None,
                date_str=None, source="manual", estimated_minutes=None,
                carried_from=None, blueprint_unit_id=None,
                energy_level=None, suggested_slot=None,
                task_type="normal", spaced_review_id=None):
    if date_str is None:
        date_str = date.today().isoformat()
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO daily_tasks
               (title, description, priority, goal_id, date, source, estimated_minutes,
                carried_from, blueprint_unit_id, energy_level, suggested_slot,
                task_type, spaced_review_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, priority, goal_id, date_str, source, estimated_minutes,
             carried_from, blueprint_unit_id, energy_level, suggested_slot,
             task_type, spaced_review_id),
        )
        task_id = cur.lastrowid
    conn.close()
    return get_task(task_id)


def get_task(task_id):
    conn = get_connection()
    row = conn.execute(
        """SELECT t.*, g.title AS goal_title,
                  (SELECT COUNT(*) FROM daily_tasks t2
                   WHERE t2.title = t.title AND t2.carried_from IS NOT NULL) AS carry_count
           FROM daily_tasks t
           LEFT JOIN goals g ON t.goal_id = g.id
           WHERE t.id = ?""",
        (task_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["is_carried"] = bool(d.get("carried_from"))
    return d


def get_tasks_for_date(date_str):
    conn = get_connection()
    rows = conn.execute(
        """SELECT t.*, g.title AS goal_title,
                  (SELECT COUNT(*) FROM daily_tasks t2
                   WHERE t2.title = t.title AND t2.carried_from IS NOT NULL) AS carry_count
           FROM daily_tasks t
           LEFT JOIN goals g ON t.goal_id = g.id
           WHERE t.date = ?
           ORDER BY t.completed ASC, t.priority DESC, t.created_at ASC""",
        (date_str,),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["is_carried"] = bool(d.get("carried_from"))
        result.append(d)
    return result


def get_yesterday_incomplete_count():
    """Return count of yesterday's incomplete tasks that aren't already carried today."""
    conn = get_connection()
    row = conn.execute(
        """SELECT COUNT(*) AS cnt FROM daily_tasks
           WHERE date = date('now', '-1 day')
             AND completed = 0
             AND title NOT IN (
               SELECT title FROM daily_tasks
               WHERE date = date('now') AND carried_from IS NOT NULL
             )"""
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def carry_forward_tasks():
    """Copy yesterday's incomplete tasks to today with carried_from set."""
    conn = get_connection()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()

    rows = conn.execute(
        """SELECT * FROM daily_tasks
           WHERE date = ? AND completed = 0""",
        (yesterday,),
    ).fetchall()

    created = []
    for row in rows:
        t = dict(row)
        # Skip if already carried forward today
        exists = conn.execute(
            """SELECT id FROM daily_tasks
               WHERE date = ? AND title = ? AND carried_from = ?""",
            (today, t["title"], yesterday),
        ).fetchone()
        if exists:
            continue
        with conn:
            cur = conn.execute(
                """INSERT INTO daily_tasks
                   (title, description, priority, goal_id, date, source, estimated_minutes, carried_from)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (t["title"], t["description"], t["priority"], t["goal_id"],
                 today, t["source"], t["estimated_minutes"], yesterday),
            )
            new_id = cur.lastrowid
        task = get_task(new_id)
        if task:
            created.append(task)

    conn.close()
    return created


def toggle_task(task_id):
    conn = get_connection()
    with conn:
        row = conn.execute(
            "SELECT completed, blueprint_unit_id, estimated_minutes FROM daily_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            conn.close()
            return None
        new_completed = 0 if row["completed"] else 1
        completed_at = datetime.utcnow().isoformat() if new_completed else None
        conn.execute(
            "UPDATE daily_tasks SET completed = ?, completed_at = ? WHERE id = ?",
            (new_completed, completed_at, task_id),
        )
    conn.close()
    # When a task linked to a blueprint unit is marked done, update the unit and pace
    if new_completed and row["blueprint_unit_id"]:
        complete_blueprint_unit(row["blueprint_unit_id"], row["estimated_minutes"])
    return get_task(task_id)


def delete_task(task_id):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM daily_tasks WHERE id = ?", (task_id,))
    conn.close()


# ---------------------------------------------------------------------------
# History (for LLM context)
# ---------------------------------------------------------------------------

def get_recent_task_history(days=7):
    """Return task completion data for the last N days."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT date,
                  COUNT(*) AS total,
                  SUM(completed) AS completed_count,
                  GROUP_CONCAT(CASE WHEN completed = 1 THEN title END, '|') AS completed_titles
           FROM daily_tasks
           WHERE date >= date('now', ?)
           GROUP BY date
           ORDER BY date DESC""",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["completed_titles"] = [t for t in (d["completed_titles"] or "").split("|") if t]
        result.append(d)
    return result


def get_day_of_week_patterns():
    """Return average completion rates by day of week, ordered Mon-Sun."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT
               CASE strftime('%w', date)
                   WHEN '0' THEN 'Sunday'
                   WHEN '1' THEN 'Monday'
                   WHEN '2' THEN 'Tuesday'
                   WHEN '3' THEN 'Wednesday'
                   WHEN '4' THEN 'Thursday'
                   WHEN '5' THEN 'Friday'
                   WHEN '6' THEN 'Saturday'
               END AS day_name,
               strftime('%w', date) AS dow_num,
               ROUND(AVG(CAST(completed_count AS FLOAT) / NULLIF(total, 0)) * 100, 1) AS avg_pct
           FROM (
               SELECT date,
                      COUNT(*) AS total,
                      SUM(completed) AS completed_count
               FROM daily_tasks
               GROUP BY date
               HAVING total > 0
           )
           GROUP BY strftime('%w', date)
           ORDER BY CAST(strftime('%w', date) AS INTEGER)"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

def get_progress_data(days=30):
    conn = get_connection()
    today = date.today()

    daily = conn.execute(
        """SELECT date,
                  COUNT(*) AS total,
                  SUM(completed) AS completed_count
           FROM daily_tasks
           WHERE date >= date('now', ?)
           GROUP BY date
           ORDER BY date ASC""",
        (f"-{days} days",),
    ).fetchall()

    goals_summary = conn.execute(
        """SELECT level, status, COUNT(*) AS cnt
           FROM goals
           GROUP BY level, status"""
    ).fetchall()

    # All-time stats
    total_completed_ever = conn.execute(
        "SELECT COUNT(*) FROM daily_tasks WHERE completed = 1"
    ).fetchone()[0]

    goals_completed_count = conn.execute(
        "SELECT COUNT(*) FROM goals WHERE status = 'completed'"
    ).fetchone()[0]

    # This week / last week rates
    monday_this_week = today - timedelta(days=today.weekday())
    monday_last_week = monday_this_week - timedelta(days=7)
    sunday_last_week = monday_this_week - timedelta(days=1)

    def week_rate(start, end):
        row = conn.execute(
            """SELECT COUNT(*) AS total, SUM(completed) AS done
               FROM daily_tasks WHERE date BETWEEN ? AND ?""",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        if row and row["total"]:
            return round((row["done"] or 0) / row["total"], 3)
        return None

    this_week_rate = week_rate(monday_this_week, today)
    last_week_rate = week_rate(monday_last_week, sunday_last_week)

    if this_week_rate is not None and last_week_rate is not None:
        if this_week_rate > last_week_rate + 0.05:
            trend = "improving"
        elif this_week_rate < last_week_rate - 0.05:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "stable"

    # Most productive day of week
    best_day_row = conn.execute(
        """SELECT
               CASE strftime('%w', date)
                   WHEN '0' THEN 'Sunday'
                   WHEN '1' THEN 'Monday'
                   WHEN '2' THEN 'Tuesday'
                   WHEN '3' THEN 'Wednesday'
                   WHEN '4' THEN 'Thursday'
                   WHEN '5' THEN 'Friday'
                   WHEN '6' THEN 'Saturday'
               END AS day_name,
               AVG(CAST(completed_count AS FLOAT) / NULLIF(total, 0)) AS avg_rate
           FROM (
               SELECT date,
                      COUNT(*) AS total,
                      SUM(completed) AS completed_count
               FROM daily_tasks
               GROUP BY date
               HAVING total > 0
           )
           GROUP BY strftime('%w', date)
           ORDER BY avg_rate DESC
           LIMIT 1"""
    ).fetchone()
    most_productive_day = best_day_row["day_name"] if best_day_row else None

    conn.close()

    daily_list = []
    total_done = 0
    total_tasks = 0
    for row in daily:
        d = dict(row)
        pct = round((d["completed_count"] or 0) / d["total"] * 100) if d["total"] else 0
        d["completion_pct"] = pct
        daily_list.append(d)
        total_done += d["completed_count"] or 0
        total_tasks += d["total"]

    # Current streak: consecutive days with >50% completion ending today/yesterday
    day_map = {r["date"]: r["completion_pct"] for r in daily_list}
    streak = 0
    check_day = today
    while True:
        ds = check_day.isoformat()
        if ds in day_map and day_map[ds] > 50:
            streak += 1
            check_day -= timedelta(days=1)
        else:
            break

    # Longest streak: need all-time data
    all_days = []
    conn2 = get_connection()
    all_rows = conn2.execute(
        """SELECT date,
                  COUNT(*) AS total,
                  SUM(completed) AS completed_count
           FROM daily_tasks
           GROUP BY date
           HAVING total > 0
           ORDER BY date ASC"""
    ).fetchall()
    conn2.close()

    day_above50 = {}
    for r in all_rows:
        pct = (r["completed_count"] or 0) / r["total"] * 100
        day_above50[r["date"]] = pct > 50

    longest = 0
    current_run = 0
    sorted_dates = sorted(day_above50.keys())
    for i, ds in enumerate(sorted_dates):
        if day_above50[ds]:
            if i > 0:
                prev = date.fromisoformat(sorted_dates[i - 1])
                curr = date.fromisoformat(ds)
                if (curr - prev).days == 1:
                    current_run += 1
                else:
                    current_run = 1
            else:
                current_run = 1
            longest = max(longest, current_run)
        else:
            current_run = 0

    overall_pct = round(total_done / total_tasks * 100) if total_tasks else 0

    return {
        "daily": daily_list,
        "streak": streak,
        "overall_completion_pct": overall_pct,
        "goals_summary": [dict(r) for r in goals_summary],
        # New fields
        "current_streak": streak,
        "longest_streak": longest,
        "this_week_rate": this_week_rate,
        "last_week_rate": last_week_rate,
        "trend": trend,
        "most_productive_day": most_productive_day,
        "total_tasks_completed": total_completed_ever,
        "goals_completed": goals_completed_count,
    }


# ---------------------------------------------------------------------------
# Daily Reflection (upsert)
# ---------------------------------------------------------------------------

def upsert_reflection(date_str, tasks_completed, tasks_total, ai_summary=None,
                      notes=None, mood=None):
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO daily_reflections
               (date, tasks_completed, tasks_total, ai_summary, notes, mood)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                   tasks_completed = excluded.tasks_completed,
                   tasks_total = excluded.tasks_total,
                   ai_summary = COALESCE(excluded.ai_summary, ai_summary),
                   notes = COALESCE(excluded.notes, notes),
                   mood = COALESCE(excluded.mood, mood)""",
            (date_str, tasks_completed, tasks_total, ai_summary, notes, mood),
        )
    conn.close()


def get_reflection_for_date(date_str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM daily_reflections WHERE date = ?", (date_str,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Weekly Reviews
# ---------------------------------------------------------------------------

def save_weekly_review(week_start, week_end, total_tasks, completed_tasks,
                       completion_rate, goals_progressed, goals_neglected,
                       ai_review, focus_areas):
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO weekly_reviews
               (week_start, week_end, total_tasks, completed_tasks, completion_rate,
                goals_progressed, goals_neglected, ai_review, focus_areas)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(week_start) DO UPDATE SET
                   week_end = excluded.week_end,
                   total_tasks = excluded.total_tasks,
                   completed_tasks = excluded.completed_tasks,
                   completion_rate = excluded.completion_rate,
                   goals_progressed = excluded.goals_progressed,
                   goals_neglected = excluded.goals_neglected,
                   ai_review = excluded.ai_review,
                   focus_areas = excluded.focus_areas""",
            (week_start, week_end, total_tasks, completed_tasks, completion_rate,
             json.dumps(goals_progressed), json.dumps(goals_neglected),
             ai_review, json.dumps(focus_areas)),
        )
    conn.close()
    return get_weekly_review(week_start)


def get_weekly_review(week_start):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM weekly_reviews WHERE week_start = ?", (week_start,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for field in ("goals_progressed", "goals_neglected", "focus_areas"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass
    return d


def list_weekly_reviews():
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, week_start, week_end, completion_rate
           FROM weekly_reviews ORDER BY week_start DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_week_data(week_start_str, week_end_str):
    """Return all tasks and reflections for a week, used for weekly review generation."""
    conn = get_connection()
    tasks = conn.execute(
        """SELECT t.*, g.title AS goal_title
           FROM daily_tasks t
           LEFT JOIN goals g ON t.goal_id = g.id
           WHERE t.date BETWEEN ? AND ?
           ORDER BY t.date, t.priority DESC, t.created_at""",
        (week_start_str, week_end_str),
    ).fetchall()
    reflections = conn.execute(
        "SELECT * FROM daily_reflections WHERE date BETWEEN ? AND ?",
        (week_start_str, week_end_str),
    ).fetchall()
    conn.close()
    return {
        "tasks": [dict(t) for t in tasks],
        "reflections": [dict(r) for r in reflections],
    }


def get_previous_weekly_review(before_week_start):
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM weekly_reviews WHERE week_start < ?
           ORDER BY week_start DESC LIMIT 1""",
        (before_week_start,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for field in ("goals_progressed", "goals_neglected", "focus_areas"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass
    return d


def get_recent_weekly_reviews(before_week_start, limit=4):
    """Return up to limit weekly reviews before before_week_start, newest first."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM weekly_reviews WHERE week_start < ?
           ORDER BY week_start DESC LIMIT ?""",
        (before_week_start, limit),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for field in ("goals_progressed", "goals_neglected", "focus_areas"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    pass
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# OAuth Tokens
# ---------------------------------------------------------------------------

def save_oauth_token(service, token_json, email=None):
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO oauth_tokens (service, token_json, email, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(service) DO UPDATE SET
                   token_json = excluded.token_json,
                   email = COALESCE(excluded.email, email),
                   updated_at = CURRENT_TIMESTAMP""",
            (service, token_json, email),
        )
    conn.close()


def get_oauth_token(service):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM oauth_tokens WHERE service = ?", (service,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_oauth_token(service):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM oauth_tokens WHERE service = ?", (service,))
    conn.close()


# ---------------------------------------------------------------------------
# Email Digests & Action Items
# ---------------------------------------------------------------------------

def upsert_email_digest(date_str, emails_scanned, ai_summary, raw_emails_json):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO email_digests (date, emails_scanned, ai_summary, raw_emails_json)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                   emails_scanned = excluded.emails_scanned,
                   ai_summary = excluded.ai_summary,
                   raw_emails_json = excluded.raw_emails_json""",
            (date_str, emails_scanned, ai_summary, raw_emails_json),
        )
        # Get the id of the upserted row
        row = conn.execute(
            "SELECT id FROM email_digests WHERE date = ?", (date_str,)
        ).fetchone()
        digest_id = row["id"]
    conn.close()
    return digest_id


def get_email_digest_for_date(date_str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM email_digests WHERE date = ?", (date_str,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    digest = dict(row)
    items = conn.execute(
        "SELECT * FROM email_action_items WHERE digest_id = ? ORDER BY priority DESC, created_at ASC",
        (digest["id"],),
    ).fetchall()
    conn.close()
    digest["action_items"] = [dict(i) for i in items]
    return digest


def save_email_action_items(digest_id, action_items):
    """Replace all action items for a digest (called on rescan)."""
    conn = get_connection()
    with conn:
        conn.execute(
            "DELETE FROM email_action_items WHERE digest_id = ?", (digest_id,)
        )
        for item in action_items:
            conn.execute(
                """INSERT INTO email_action_items
                   (digest_id, title, description, priority, source_subject, source_sender)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (digest_id, item.get("title"), item.get("description"),
                 item.get("priority", "medium"), item.get("source_subject"),
                 item.get("source_sender")),
            )
    conn.close()


def get_email_action_item(item_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM email_action_items WHERE id = ?", (item_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_email_action_item(item_id, status, task_id=None):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE email_action_items SET status = ?, task_id = COALESCE(?, task_id) WHERE id = ?",
            (status, task_id, item_id),
        )
    conn.close()
    return get_email_action_item(item_id)


def get_pending_email_action_items(date_str):
    """Return pending email action items for the given date."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT eai.* FROM email_action_items eai
           JOIN email_digests ed ON eai.digest_id = ed.id
           WHERE ed.date = ? AND eai.status = 'pending'
           ORDER BY eai.priority DESC, eai.created_at ASC""",
        (date_str,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Bot Config
# ---------------------------------------------------------------------------

def get_bot_config(service):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM bot_config WHERE service = ?", (service,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_bot_config(service, chat_id=None, enabled=1, settings_json=None):
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO bot_config (service, chat_id, enabled, settings_json, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(service) DO UPDATE SET
                   chat_id = COALESCE(excluded.chat_id, chat_id),
                   enabled = excluded.enabled,
                   settings_json = COALESCE(excluded.settings_json, settings_json),
                   updated_at = CURRENT_TIMESTAMP""",
            (service, chat_id, enabled, settings_json),
        )
    conn.close()
    return get_bot_config(service)


def update_bot_config(service, **fields):
    allowed = {"chat_id", "enabled", "settings_json"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_bot_config(service)
    updates["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [service]
    conn = get_connection()
    with conn:
        conn.execute(f"UPDATE bot_config SET {set_clause} WHERE service = ?", values)
    conn.close()
    return get_bot_config(service)


# ---------------------------------------------------------------------------
# Agent Logs
# ---------------------------------------------------------------------------

def get_agent_logs(agent_name=None, limit=20):
    conn = get_connection()
    if agent_name:
        rows = conn.execute(
            """SELECT id, agent_name, trigger_type, input_summary, duration_ms,
                      success, error_message, created_at
               FROM agent_logs WHERE agent_name = ?
               ORDER BY created_at DESC LIMIT ?""",
            (agent_name, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, agent_name, trigger_type, input_summary, duration_ms,
                      success, error_message, created_at
               FROM agent_logs
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_agent_log(agent_name):
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM agent_logs WHERE agent_name = ?
           ORDER BY created_at DESC LIMIT 1""",
        (agent_name,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_agents_status():
    """Return last run time and status for each agent."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT agent_name,
                  MAX(created_at) AS last_run,
                  success AS last_status
           FROM agent_logs
           GROUP BY agent_name""",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Learning Resources
# ---------------------------------------------------------------------------

def get_learning_resources(goal_id=None):
    conn = get_connection()
    if goal_id:
        rows = conn.execute(
            "SELECT * FROM learning_resources WHERE goal_id = ? ORDER BY created_at ASC",
            (goal_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM learning_resources ORDER BY created_at ASC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_learning_resource(resource_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM learning_resources WHERE id = ?", (resource_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_learning_resource(goal_id, type_, title, author=None, url=None,
                              total_units=None, unit_label="chapter", notes=None):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO learning_resources
               (goal_id, type, title, author, url, total_units, unit_label, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (goal_id, type_, title, author, url, total_units, unit_label, notes),
        )
        resource_id = cur.lastrowid
    conn.close()
    return get_learning_resource(resource_id)


def update_learning_resource(resource_id, **fields):
    allowed = {"goal_id", "type", "title", "author", "url", "total_units",
               "completed_units", "unit_label", "status", "notes"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_learning_resource(resource_id)
    updates["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [resource_id]
    conn = get_connection()
    with conn:
        conn.execute(f"UPDATE learning_resources SET {set_clause} WHERE id = ?", values)
    conn.close()
    return get_learning_resource(resource_id)


def delete_learning_resource(resource_id):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM learning_resources WHERE id = ?", (resource_id,))
    conn.close()


def get_recent_learning_tasks(days=7):
    """Return recent tasks that appear to be learning-related (keyword match)."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM daily_tasks
           WHERE date >= date('now', ?)
             AND (title LIKE '%read%' OR title LIKE '%study%' OR title LIKE '%learn%'
                  OR title LIKE '%chapter%' OR title LIKE '%course%' OR title LIKE '%practice%'
                  OR title LIKE '%review%' OR title LIKE '%exercise%')
           ORDER BY date DESC""",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Accountability Insights
# ---------------------------------------------------------------------------

def save_accountability_insight(insight_type, title, description=None,
                                 related_goal_id=None, severity="info",
                                 valid_until=None):
    """Insert an insight, skipping if an unacknowledged one with the same title exists."""
    conn = get_connection()
    existing = conn.execute(
        """SELECT id FROM accountability_insights
           WHERE title = ? AND acknowledged = 0
             AND (valid_until IS NULL OR valid_until >= date('now'))""",
        (title,),
    ).fetchone()
    if existing:
        conn.close()
        return None
    with conn:
        cur = conn.execute(
            """INSERT INTO accountability_insights
               (insight_type, title, description, related_goal_id, severity, valid_until)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (insight_type, title, description, related_goal_id, severity, valid_until),
        )
        insight_id = cur.lastrowid
    conn.close()
    return get_accountability_insight(insight_id)


def get_accountability_insight(insight_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM accountability_insights WHERE id = ?", (insight_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_active_insights(limit=20):
    """Return unacknowledged, non-expired insights, newest first."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM accountability_insights
           WHERE acknowledged = 0
             AND (valid_until IS NULL OR valid_until >= date('now'))
           ORDER BY created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def acknowledge_insight(insight_id):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE accountability_insights SET acknowledged = 1 WHERE id = ?",
            (insight_id,),
        )
    conn.close()
    return get_accountability_insight(insight_id)


# ---------------------------------------------------------------------------
# Additional helpers for agents
# ---------------------------------------------------------------------------

def get_recent_reflections(days=14):
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM daily_reflections
           WHERE date >= date('now', ?)
           ORDER BY date DESC""",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_goal_last_activity():
    """Return {goal_id: last_completed_date} for all goals that have tasks."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT goal_id, MAX(completed_at) AS last_completed
           FROM daily_tasks
           WHERE completed = 1 AND goal_id IS NOT NULL
           GROUP BY goal_id"""
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        if r["last_completed"]:
            # completed_at is a full datetime; take just the date part
            result[r["goal_id"]] = r["last_completed"][:10]
    return result


# ---------------------------------------------------------------------------
# Phase 6 — Goal Blueprints
# ---------------------------------------------------------------------------

def create_blueprint(goal_id, blueprint_type, title, source_info=None,
                     total_units=0, unit_label="unit", schedule_strategy="even",
                     difficulty_curve=None, estimated_pace_minutes=None):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO goal_blueprints
               (goal_id, blueprint_type, title, source_info, total_units, unit_label,
                schedule_strategy, difficulty_curve, estimated_pace_minutes, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            (
                goal_id, blueprint_type, title,
                json.dumps(source_info) if source_info and not isinstance(source_info, str) else source_info,
                total_units, unit_label, schedule_strategy,
                json.dumps(difficulty_curve) if difficulty_curve and not isinstance(difficulty_curve, str) else difficulty_curve,
                estimated_pace_minutes,
            ),
        )
        bp_id = cur.lastrowid
    conn.close()
    return get_blueprint(bp_id)


def get_blueprint(blueprint_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM goal_blueprints WHERE id = ?", (blueprint_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    bp = dict(row)
    milestones = conn.execute(
        "SELECT * FROM blueprint_milestones WHERE blueprint_id = ? ORDER BY sort_order",
        (blueprint_id,),
    ).fetchall()
    bp["milestones"] = [dict(m) for m in milestones]
    counts = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM blueprint_units WHERE blueprint_id = ? GROUP BY status",
        (blueprint_id,),
    ).fetchall()
    bp["unit_counts"] = {r["status"]: r["cnt"] for r in counts}
    conn.close()
    return bp


def get_blueprint_by_goal(goal_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM goal_blueprints WHERE goal_id = ?", (goal_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return get_blueprint(row["id"])


def update_blueprint(blueprint_id, **fields):
    allowed = {
        "title", "blueprint_type", "source_info", "total_units", "unit_label",
        "schedule_strategy", "difficulty_curve", "estimated_pace_minutes",
        "actual_pace_minutes", "pace_samples", "completed_units", "status",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_blueprint(blueprint_id)
    updates["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [blueprint_id]
    conn = get_connection()
    with conn:
        conn.execute(f"UPDATE goal_blueprints SET {set_clause} WHERE id = ?", values)
    conn.close()
    return get_blueprint(blueprint_id)


# ---------------------------------------------------------------------------
# Phase 6 — Blueprint Milestones
# ---------------------------------------------------------------------------

def create_milestone(blueprint_id, title, description=None, target_date=None, sort_order=0):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO blueprint_milestones (blueprint_id, title, description, target_date, sort_order)
               VALUES (?, ?, ?, ?, ?)""",
            (blueprint_id, title, description, target_date, sort_order),
        )
        ms_id = cur.lastrowid
    conn.close()
    return get_milestone(ms_id)


def get_milestone(milestone_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM blueprint_milestones WHERE id = ?", (milestone_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_milestones(blueprint_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM blueprint_milestones WHERE blueprint_id = ? ORDER BY sort_order",
        (blueprint_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Phase 6 — Blueprint Units
# ---------------------------------------------------------------------------

def create_blueprint_unit(blueprint_id, unit_number, title, description=None,
                           milestone_id=None, estimated_minutes=None,
                           difficulty=1.0, depends_on=None, metadata=None):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO blueprint_units
               (blueprint_id, milestone_id, title, description, unit_number,
                estimated_minutes, difficulty, depends_on, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                blueprint_id, milestone_id, title, description, unit_number,
                estimated_minutes, difficulty, depends_on,
                json.dumps(metadata) if metadata and not isinstance(metadata, str) else metadata,
            ),
        )
        unit_id = cur.lastrowid
    conn.close()
    return get_blueprint_unit(unit_id)


def get_blueprint_unit(unit_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM blueprint_units WHERE id = ?", (unit_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_blueprint_units(blueprint_id, status_filter=None):
    conn = get_connection()
    if status_filter:
        placeholders = ",".join("?" * len(status_filter))
        rows = conn.execute(
            f"""SELECT * FROM blueprint_units
               WHERE blueprint_id = ? AND status IN ({placeholders})
               ORDER BY unit_number""",
            (blueprint_id, *status_filter),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM blueprint_units WHERE blueprint_id = ? ORDER BY unit_number",
            (blueprint_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_units_scheduled_today():
    """Return all blueprint units scheduled for today that are not yet completed."""
    today = date.today().isoformat()
    conn = get_connection()
    rows = conn.execute(
        """SELECT u.*, b.goal_id, b.blueprint_type, b.unit_label,
                  b.actual_pace_minutes, b.estimated_pace_minutes,
                  g.title AS goal_title
           FROM blueprint_units u
           JOIN goal_blueprints b ON u.blueprint_id = b.id
           JOIN goals g ON b.goal_id = g.id
           WHERE u.scheduled_date = ? AND u.status IN ('pending', 'in_progress')
             AND b.status = 'active'
           ORDER BY u.blueprint_id, u.unit_number""",
        (today,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def complete_blueprint_unit(unit_id, actual_minutes=None):
    conn = get_connection()
    unit_row = conn.execute(
        "SELECT * FROM blueprint_units WHERE id = ?", (unit_id,)
    ).fetchone()
    if not unit_row:
        conn.close()
        return None
    unit = dict(unit_row)

    # Skip if already completed/skipped
    if unit["status"] in ("completed", "skipped"):
        conn.close()
        return unit

    now = datetime.utcnow().isoformat()
    with conn:
        conn.execute(
            "UPDATE blueprint_units SET status='completed', completed_at=?, actual_minutes=? WHERE id=?",
            (now, actual_minutes, unit_id),
        )
        conn.execute(
            "UPDATE goal_blueprints SET completed_units=completed_units+1, updated_at=? WHERE id=?",
            (now, unit["blueprint_id"]),
        )
        if actual_minutes is not None:
            bp_row = conn.execute(
                "SELECT actual_pace_minutes, pace_samples FROM goal_blueprints WHERE id=?",
                (unit["blueprint_id"],),
            ).fetchone()
            if bp_row:
                samples = bp_row["pace_samples"] or 0
                old_pace = bp_row["actual_pace_minutes"]
                if samples == 0 or old_pace is None:
                    new_pace = float(actual_minutes)
                else:
                    new_pace = old_pace * 0.7 + actual_minutes * 0.3
                conn.execute(
                    "UPDATE goal_blueprints SET actual_pace_minutes=?, pace_samples=pace_samples+1 WHERE id=?",
                    (new_pace, unit["blueprint_id"]),
                )
        # Auto-complete milestone if all its units are done
        if unit.get("milestone_id"):
            pending = conn.execute(
                """SELECT COUNT(*) FROM blueprint_units
                   WHERE milestone_id=? AND status NOT IN ('completed','skipped')""",
                (unit["milestone_id"],),
            ).fetchone()[0]
            if pending == 0:
                conn.execute(
                    "UPDATE blueprint_milestones SET completed=1, completed_at=? WHERE id=?",
                    (now, unit["milestone_id"]),
                )

    result = dict(
        conn.execute("SELECT * FROM blueprint_units WHERE id=?", (unit_id,)).fetchone()
    )
    conn.close()

    # Only schedule reviews for learning blueprints
    bp = get_blueprint(unit["blueprint_id"])
    if bp and bp.get("blueprint_type") == "learning":
        schedule_reviews(unit_id, date.today())

    return result


def skip_blueprint_unit(unit_id):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE blueprint_units SET status='skipped' WHERE id=?",
            (unit_id,),
        )
    result = dict(
        conn.execute("SELECT * FROM blueprint_units WHERE id=?", (unit_id,)).fetchone()
    )
    conn.close()
    return result


def get_blueprint_schedule_status(blueprint_id):
    """Return on_track / behind_N / ahead_N based on overdue pending units."""
    today = date.today().isoformat()
    conn = get_connection()
    overdue = conn.execute(
        """SELECT COUNT(*) FROM blueprint_units
           WHERE blueprint_id=? AND status='pending' AND scheduled_date < ?""",
        (blueprint_id, today),
    ).fetchone()[0]
    conn.close()
    if overdue == 0:
        return "on_track"
    return f"behind_{overdue}"


# ---------------------------------------------------------------------------
# Phase 6 — Habit Config
# ---------------------------------------------------------------------------

def create_habit_config(blueprint_id, frequency, progression_type="constant",
                         base_quantity=None, current_quantity=None, target_quantity=None,
                         quantity_unit=None, increment_amount=None,
                         increment_frequency="weekly", custom_days=None):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO habit_config
               (blueprint_id, frequency, custom_days, progression_type, base_quantity,
                current_quantity, target_quantity, quantity_unit, increment_amount,
                increment_frequency)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                blueprint_id, frequency,
                json.dumps(custom_days) if custom_days and not isinstance(custom_days, str) else custom_days,
                progression_type, base_quantity,
                current_quantity if current_quantity is not None else base_quantity,
                target_quantity, quantity_unit, increment_amount, increment_frequency,
            ),
        )
        hc_id = cur.lastrowid
    conn.close()
    return get_habit_config_by_id(hc_id)


def get_habit_config_by_id(habit_config_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM habit_config WHERE id = ?", (habit_config_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_habit_config(blueprint_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM habit_config WHERE blueprint_id = ?", (blueprint_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_habits():
    """Return all active habit configs with their blueprint and goal info."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT h.*, b.title AS blueprint_title, b.goal_id, b.status AS blueprint_status,
                  g.title AS goal_title
           FROM habit_config h
           JOIN goal_blueprints b ON h.blueprint_id = b.id
           JOIN goals g ON b.goal_id = g.id
           WHERE b.status = 'active'
           ORDER BY b.created_at""",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_habit_quantity(habit_config_id, new_quantity):
    conn = get_connection()
    today = date.today().isoformat()
    with conn:
        conn.execute(
            "UPDATE habit_config SET current_quantity=?, last_increment_date=? WHERE id=?",
            (new_quantity, today, habit_config_id),
        )
    conn.close()
    return get_habit_config_by_id(habit_config_id)


def check_habit_progression():
    """Increment current_quantity for progressive habits when due."""
    from datetime import date as _date, timedelta
    today = _date.today()
    conn = get_connection()
    habits = conn.execute(
        """SELECT h.* FROM habit_config h
           JOIN goal_blueprints b ON h.blueprint_id = b.id
           WHERE h.progression_type = 'progressive' AND b.status = 'active'""",
    ).fetchall()
    updated = []
    for h in habits:
        h = dict(h)
        if h["target_quantity"] is None:
            continue
        if h["current_quantity"] is not None and h["current_quantity"] >= h["target_quantity"]:
            continue
        last = h["last_increment_date"]
        freq = h["increment_frequency"] or "weekly"
        delta = {"daily": 1, "weekly": 7, "biweekly": 14, "monthly": 30}.get(freq, 7)
        if last is None or (_date.today() - _date.fromisoformat(last)).days >= delta:
            inc = h["increment_amount"] or 0
            new_qty = min((h["current_quantity"] or h["base_quantity"] or 0) + inc,
                          h["target_quantity"])
            with conn:
                conn.execute(
                    "UPDATE habit_config SET current_quantity=?, last_increment_date=? WHERE id=?",
                    (new_qty, today.isoformat(), h["id"]),
                )
            updated.append(h["id"])
    conn.close()
    return updated


def get_habit_streak(blueprint_id):
    """Count consecutive completed units going backwards from the most recent scheduled one."""
    conn = get_connection()
    units = conn.execute(
        """SELECT status FROM blueprint_units
           WHERE blueprint_id=? AND scheduled_date IS NOT NULL
           ORDER BY scheduled_date DESC""",
        (blueprint_id,),
    ).fetchall()
    conn.close()
    streak = 0
    for u in units:
        if u["status"] == "completed":
            streak += 1
        else:
            break
    return streak


def get_today_habit_unit(blueprint_id):
    """Return today's pending/in_progress unit for a habit blueprint, falling back to most recent overdue."""
    from datetime import date as _date
    today = _date.today().isoformat()
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM blueprint_units
           WHERE blueprint_id=? AND scheduled_date=? AND status IN ('pending','in_progress')
           ORDER BY unit_number LIMIT 1""",
        (blueprint_id, today),
    ).fetchone()
    if not row:
        row = conn.execute(
            """SELECT * FROM blueprint_units
               WHERE blueprint_id=? AND scheduled_date < ? AND status IN ('pending','in_progress')
               ORDER BY scheduled_date DESC LIMIT 1""",
            (blueprint_id, today),
        ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Phase 6 — Career Pipeline
# ---------------------------------------------------------------------------

def create_pipeline_entry(blueprint_id, entry_type, title, company=None,
                           status=None, url=None, notes=None,
                           deadline=None, follow_up_date=None):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO career_pipeline
               (blueprint_id, entry_type, title, company, status, url, notes, deadline, follow_up_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (blueprint_id, entry_type, title, company, status, url, notes, deadline, follow_up_date),
        )
        entry_id = cur.lastrowid
    conn.close()
    return get_pipeline_entry(entry_id)


def get_pipeline_entry(entry_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM career_pipeline WHERE id = ?", (entry_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_pipeline_entries(blueprint_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM career_pipeline WHERE blueprint_id = ? ORDER BY created_at DESC",
        (blueprint_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_pipeline_entry(entry_id, **fields):
    allowed = {"entry_type", "title", "company", "status", "url", "notes", "deadline", "follow_up_date"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_pipeline_entry(entry_id)
    updates["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [entry_id]
    conn = get_connection()
    with conn:
        conn.execute(f"UPDATE career_pipeline SET {set_clause} WHERE id = ?", values)
    conn.close()
    return get_pipeline_entry(entry_id)


# ---------------------------------------------------------------------------
# User Profile
# ---------------------------------------------------------------------------

def get_user_profile():
    """Return profile as {category: {key: {value, confidence, data_points, last_updated}}}."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM user_profile ORDER BY category, key"
    ).fetchall()
    conn.close()
    profile = {}
    for r in rows:
        cat = r["category"]
        if cat not in profile:
            profile[cat] = {}
        profile[cat][r["key"]] = {
            "value": r["value"],
            "confidence": r["confidence"],
            "data_points": r["data_points"],
            "last_updated": r["last_updated"],
        }
    return profile


def upsert_profile_entry(category, key, value, confidence=0.5, data_points=1):
    """Insert or update a single profile entry."""
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO user_profile (category, key, value, confidence, data_points, last_updated)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(category, key) DO UPDATE SET
                   value = excluded.value,
                   confidence = excluded.confidence,
                   data_points = excluded.data_points,
                   last_updated = CURRENT_TIMESTAMP""",
            (category, key, value, confidence, data_points),
        )
    conn.close()


def get_profile_value(category, key, default=None):
    """Return the value for a profile key, or default if not found."""
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM user_profile WHERE category = ? AND key = ?",
        (category, key),
    ).fetchone()
    conn.close()
    return row["value"] if row else default


def get_profile_for_prompt():
    """Return a formatted profile text block for injection into agent prompts.
    Returns empty string if no profile data exists yet."""
    profile = get_user_profile()
    if not profile:
        return ""

    total_entries = sum(len(keys) for keys in profile.values())
    if total_entries < 3:
        return "\n## User Profile\n(Still learning your patterns — not enough data yet)\n"

    _category_labels = {
        "work_style": "Work Style",
        "goal_tendencies": "Goal Tendencies",
        "scheduling": "Scheduling",
        "learning": "Learning",
        "emotional": "Emotional",
    }
    _key_labels = {
        "peak_hours": "Peak hours",
        "max_deep_work_hours": "Max deep work hours",
        "max_tasks_per_day": "Max tasks per day",
        "preferred_task_sequence": "Task sequence preference",
        "focus_duration_minutes": "Focus duration (min)",
        "context_switch_cost": "Context switching cost",
        "avoidance_pattern": "Completion rate by goal type",
        "procrastination_triggers": "Tends to avoid",
        "momentum_builder": "Motivated by",
        "abandonment_risk_signals": "Abandonment risk signals",
        "day_ratings": "Day ratings",
        "best_streak_day": "Best day",
        "worst_day": "Worst day",
        "overload_threshold": "Overload threshold (tasks)",
        "recovery_pattern": "After a bad day",
        "retention_strength": "Retention strength",
        "preferred_learning_format": "Learning format",
        "review_compliance": "Review compliance rate",
        "best_learning_time": "Best learning time",
        "chapters_before_fatigue": "Chapters before fatigue",
        "mood_trend": "Current mood trend",
        "mood_productivity_correlation": "Mood-productivity correlation",
        "bad_day_response": "Bad day response",
        "praise_effectiveness": "Encouragement effectiveness",
        "accountability_response": "Responds to accountability",
    }

    lines = ["## User Profile (what we know about this person)\n"]
    for category, keys in profile.items():
        label = _category_labels.get(category, category.replace("_", " ").title())
        lines.append(f"{label}:")
        for key, data in keys.items():
            confidence_pct = int(data["confidence"] * 100)
            key_label = _key_labels.get(key, key.replace("_", " ").title())
            value = data["value"]
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    value = ", ".join(f"{k}: {v}" for k, v in parsed.items())
                elif isinstance(parsed, list):
                    value = ", ".join(str(v) for v in parsed)
            except Exception:
                pass
            lines.append(f"- {key_label}: {value} (confidence: {confidence_pct}%)")
        lines.append("")

    lines.append(
        "Use this profile to personalize your output. "
        "Low-confidence items are hypotheses; high-confidence items are established patterns."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reflection Memory (Upgrade 3)
# ---------------------------------------------------------------------------

def get_active_suggestions(limit=10):
    """Return active suggestions ordered by escalation_level DESC."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM reflection_memory
           WHERE status IN ('active', 'escalated')
           ORDER BY escalation_level DESC, last_given DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_suggestion(suggestion_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM reflection_memory WHERE id = ?", (suggestion_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_suggestion(suggestion_text, category=None, related_goal_id=None, given_date=None):
    """Create a new suggestion entry."""
    today = given_date or date.today().isoformat()
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO reflection_memory
               (suggestion, suggestion_category, related_goal_id,
                times_given, times_followed, first_given, last_given,
                follow_through_rate, status, escalation_level)
               VALUES (?, ?, ?, 1, 0, ?, ?, 0.0, 'active', 0)""",
            (suggestion_text, category, related_goal_id, today, today),
        )
        sid = cur.lastrowid
    conn.close()
    return get_suggestion(sid)


def update_suggestion_after_review(suggestion_id, followed, new_escalation_level=None,
                                    given_date=None):
    """Increment counters, recompute follow_through_rate, optionally update escalation."""
    s = get_suggestion(suggestion_id)
    if not s:
        return None
    today = given_date or date.today().isoformat()
    new_times_given = s["times_given"] + 1
    new_times_followed = s["times_followed"] + (1 if followed else 0)
    rate = new_times_followed / new_times_given

    # Auto-escalate if not followed repeatedly
    level = s["escalation_level"]
    if new_escalation_level is not None:
        level = max(level, new_escalation_level)
    elif not followed and new_times_given >= 3 and rate < 0.3:
        level = min(3, level + 1)

    new_status = "escalated" if level >= 1 else "active"

    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE reflection_memory
               SET times_given=?, times_followed=?, follow_through_rate=?,
                   escalation_level=?, status=?, last_given=?
               WHERE id=?""",
            (new_times_given, new_times_followed, rate, level, new_status, today, suggestion_id),
        )
    conn.close()
    return get_suggestion(suggestion_id)


def resolve_suggestion(suggestion_id):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE reflection_memory SET status='resolved' WHERE id=?", (suggestion_id,)
        )
    conn.close()


def drop_suggestion(suggestion_id):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE reflection_memory SET status='dropped' WHERE id=?", (suggestion_id,)
        )
    conn.close()


def reset_suggestion_escalation(suggestion_id):
    """Reset escalation to 0 when user confirms the goal is still important."""
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE reflection_memory SET escalation_level=0, status='active' WHERE id=?",
            (suggestion_id,),
        )
    conn.close()


# ---------------------------------------------------------------------------
# Energy Curve
# ---------------------------------------------------------------------------

_ENERGY_CURVE_DEFAULTS = {
    "id": None,
    "user_defined": False,
    "slot_1_label": "Early Morning",
    "slot_1_energy": "medium",
    "slot_2_label": "Morning",
    "slot_2_energy": "high",
    "slot_3_label": "Early Afternoon",
    "slot_3_energy": "low",
    "slot_4_label": "Late Afternoon",
    "slot_4_energy": "medium",
    "slot_5_label": "Evening",
    "slot_5_energy": "medium",
    "updated_at": None,
}


def get_energy_curve():
    """Return the saved energy curve row, or defaults if none exists."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM energy_curve ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else dict(_ENERGY_CURVE_DEFAULTS)


def upsert_energy_curve(user_defined=True, slot_1_energy="medium", slot_2_energy="high",
                         slot_3_energy="low", slot_4_energy="medium", slot_5_energy="medium"):
    """Save energy curve settings (always a single row)."""
    conn = get_connection()
    existing = conn.execute("SELECT id FROM energy_curve LIMIT 1").fetchone()
    if existing:
        with conn:
            conn.execute(
                """UPDATE energy_curve
                   SET user_defined=?, slot_1_energy=?, slot_2_energy=?,
                       slot_3_energy=?, slot_4_energy=?, slot_5_energy=?,
                       updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (user_defined, slot_1_energy, slot_2_energy, slot_3_energy,
                 slot_4_energy, slot_5_energy, existing["id"]),
            )
    else:
        with conn:
            conn.execute(
                """INSERT INTO energy_curve
                   (user_defined, slot_1_energy, slot_2_energy,
                    slot_3_energy, slot_4_energy, slot_5_energy)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_defined, slot_1_energy, slot_2_energy,
                 slot_3_energy, slot_4_energy, slot_5_energy),
            )
    conn.close()
    return get_energy_curve()


def detect_energy_curve_from_history():
    """Analyze completed_at timestamps to infer energy levels per time slot.
    Returns {1..5: energy_str} or None if fewer than 10 completions in last 30 days."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT completed_at FROM daily_tasks
           WHERE completed = 1 AND completed_at IS NOT NULL
             AND date >= date('now', '-30 days')"""
    ).fetchall()
    conn.close()

    slot_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in rows:
        try:
            hour = int(r["completed_at"][11:13])
            if 6 <= hour < 9:
                slot_counts[1] += 1
            elif 9 <= hour < 12:
                slot_counts[2] += 1
            elif 12 <= hour < 15:
                slot_counts[3] += 1
            elif 15 <= hour < 18:
                slot_counts[4] += 1
            elif 18 <= hour < 21:
                slot_counts[5] += 1
        except Exception:
            pass

    total = sum(slot_counts.values())
    if total < 10:
        return None

    max_count = max(slot_counts.values()) or 1
    result = {}
    for slot, count in slot_counts.items():
        ratio = count / max_count
        if ratio >= 0.6:
            result[slot] = "high"
        elif ratio >= 0.25:
            result[slot] = "medium"
        else:
            result[slot] = "low"
    return result


# ---------------------------------------------------------------------------
# Spaced Repetition (Upgrade 4)
# ---------------------------------------------------------------------------

def schedule_reviews(unit_id, completion_date):
    """Schedule spaced review sessions after a learning unit is completed."""
    retention = get_profile_value("learning", "retention_strength", default="moderate")
    try:
        compliance = float(get_profile_value("learning", "review_compliance", default="0.5"))
    except (TypeError, ValueError):
        compliance = 0.5

    if retention == "weak":
        intervals = [1, 2, 5, 10, 21]
    elif retention == "strong":
        intervals = [1, 4, 10, 21, 45]
    else:
        intervals = [1, 3, 7, 14, 30]

    if compliance < 0.3:
        intervals = intervals[:3]

    conn = get_connection()
    # Don't create duplicate reviews for this unit
    existing = conn.execute(
        "SELECT COUNT(*) FROM spaced_reviews WHERE blueprint_unit_id=?", (unit_id,)
    ).fetchone()[0]
    if existing > 0:
        conn.close()
        return

    with conn:
        for i, days in enumerate(intervals):
            review_date = (completion_date + timedelta(days=days)).isoformat()
            conn.execute(
                """INSERT INTO spaced_reviews (blueprint_unit_id, review_number, scheduled_date)
                   VALUES (?, ?, ?)""",
                (unit_id, i + 1, review_date),
            )
    conn.close()


def get_due_spaced_reviews(date_str=None, limit=2):
    """Return uncompleted reviews due on or before date_str, capped at limit."""
    if date_str is None:
        date_str = date.today().isoformat()
    conn = get_connection()
    rows = conn.execute(
        """SELECT sr.*, u.title AS unit_title, u.description AS unit_description,
                  u.metadata AS unit_metadata,
                  b.title AS blueprint_title, b.blueprint_type,
                  g.title AS goal_title
           FROM spaced_reviews sr
           JOIN blueprint_units u ON sr.blueprint_unit_id = u.id
           JOIN goal_blueprints b ON u.blueprint_id = b.id
           JOIN goals g ON b.goal_id = g.id
           WHERE sr.completed = 0 AND sr.scheduled_date <= ?
             AND b.status = 'active'
           ORDER BY sr.quality_rating ASC NULLS FIRST, sr.scheduled_date ASC
           LIMIT ?""",
        (date_str, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def complete_spaced_review(review_id, quality_rating):
    """Mark a review complete and reschedule if recall was poor."""
    conn = get_connection()
    review_row = conn.execute(
        "SELECT * FROM spaced_reviews WHERE id=?", (review_id,)
    ).fetchone()
    if not review_row:
        conn.close()
        return None
    review = dict(review_row)

    now = datetime.utcnow().isoformat()
    with conn:
        conn.execute(
            "UPDATE spaced_reviews SET completed=1, completed_at=?, quality_rating=? WHERE id=?",
            (now, quality_rating, review_id),
        )

    # Adjust the next scheduled review for this unit based on quality
    next_review = conn.execute(
        """SELECT * FROM spaced_reviews
           WHERE blueprint_unit_id=? AND completed=0
           ORDER BY review_number ASC LIMIT 1""",
        (review["blueprint_unit_id"],),
    ).fetchone()

    if next_review:
        next_review = dict(next_review)
        try:
            next_date = date.fromisoformat(next_review["scheduled_date"])
            today = date.today()
            current_interval = (next_date - today).days

            if quality_rating == 1:
                new_date = today + timedelta(days=1)
            elif quality_rating == 2:
                new_interval = max(1, int(current_interval * 0.5))
                new_date = today + timedelta(days=new_interval)
            elif quality_rating == 5:
                new_interval = int(current_interval * 1.5)
                new_date = today + timedelta(days=new_interval)
            else:
                new_date = next_date

            with conn:
                conn.execute(
                    "UPDATE spaced_reviews SET scheduled_date=? WHERE id=?",
                    (new_date.isoformat(), next_review["id"]),
                )
        except Exception:
            pass

    conn.close()
    return review


def get_spaced_review_compliance(days=30):
    """Return completed/scheduled ratio for spaced reviews in the last N days."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = get_connection()
    row = conn.execute(
        """SELECT
               COUNT(*) AS total,
               SUM(completed) AS done
           FROM spaced_reviews
           WHERE scheduled_date >= ?""",
        (cutoff,),
    ).fetchone()
    conn.close()
    if not row or not row["total"]:
        return None
    return round(row["done"] / row["total"], 3)


# Load Balancing (Upgrade 5)
# ---------------------------------------------------------------------------

def calculate_daily_capacity(target_date=None):
    """Estimate productive minutes for target_date, accounting for profile + history.

    Returns:
        {total_capacity_minutes, already_scheduled_minutes, remaining_minutes,
         day_quality ('high'|'medium'|'low'), notes (str or None)}
    """
    if target_date is None:
        target_date = date.today()

    base_capacity = 240  # 4-hour baseline

    # Day-of-week factor from profile (or fall back to historical patterns)
    _abbrevs = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    day_abbrev = _abbrevs[target_date.weekday()]
    day_rating = 0.7

    try:
        day_ratings_json = get_profile_value("scheduling", "day_ratings")
        if day_ratings_json:
            day_ratings = json.loads(day_ratings_json)
            day_rating = float(day_ratings.get(day_abbrev, 0.7))
        else:
            patterns = get_day_of_week_patterns()
            day_name = target_date.strftime("%A")
            match = next((p for p in patterns if p["day_name"] == day_name), None)
            if match and match.get("avg_pct"):
                day_rating = match["avg_pct"] / 100.0
    except Exception:
        pass

    capacity = base_capacity * day_rating

    # Recovery factor — check yesterday's load vs overload threshold
    recovery_needed = False
    recovery_pattern = get_profile_value("scheduling", "recovery_pattern", default="bounces_back")
    if recovery_pattern == "after_bad_day_needs_easy_day":
        try:
            overload_threshold = int(get_profile_value("scheduling", "overload_threshold", default="5"))
        except (TypeError, ValueError):
            overload_threshold = 5
        yesterday = (target_date - timedelta(days=1)).isoformat()
        conn = get_connection()
        yesterday_total = conn.execute(
            "SELECT COUNT(*) FROM daily_tasks WHERE date = ?", (yesterday,)
        ).fetchone()[0]
        conn.close()
        if yesterday_total > overload_threshold:
            recovery_needed = True
            capacity *= 0.6

    # Mood factor
    mood_trend = get_profile_value("emotional", "mood_trend", default="stable")
    if mood_trend == "declining":
        capacity *= 0.8

    # Streak factor (last 3 days in history, ordered most-recent first)
    streak_broke = False
    history = get_recent_task_history(days=5)
    recent = [h for h in history if h["date"] < target_date.isoformat()][:3]
    if len(recent) >= 3:
        rates = []
        for h in recent:
            total = h.get("total", 0)
            done = h.get("completed_count") or 0
            rates.append(done / total if total > 0 else 0.0)
        if all(r >= 0.7 for r in rates):
            capacity = min(capacity * 1.05, base_capacity * 1.1)
        elif rates[0] < 0.5 and rates[1] >= 0.7:
            streak_broke = True
            capacity *= 0.9

    # Already-scheduled minutes for target_date
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(SUM(estimated_minutes), 0) AS total FROM daily_tasks WHERE date = ?",
        (target_date.isoformat(),),
    ).fetchone()
    conn.close()
    existing_minutes = int(row["total"]) if row else 0

    remaining = max(0, int(capacity) - existing_minutes)
    day_quality = "high" if day_rating > 0.7 else "medium" if day_rating > 0.5 else "low"

    notes = []
    if recovery_needed:
        notes.append("Recovery day — keep it light")
    if mood_trend == "declining":
        notes.append("Mood declining — reduce expectations")
    if streak_broke:
        notes.append("Streak just broke — make today easy to rebuild")
    if day_quality == "low" and not recovery_needed:
        notes.append(f"{target_date.strftime('%A')}s are historically low-output for you")

    return {
        "total_capacity_minutes": int(capacity),
        "already_scheduled_minutes": existing_minutes,
        "remaining_minutes": remaining,
        "day_quality": day_quality,
        "notes": "; ".join(notes) if notes else None,
    }


def get_pipeline_stats(blueprint_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT entry_type, status, COUNT(*) AS cnt FROM career_pipeline WHERE blueprint_id=? GROUP BY entry_type, status",
        (blueprint_id,),
    ).fetchall()
    conn.close()
    stats = {"total_applications": 0, "interviews": 0, "offers": 0, "rejections": 0}
    for r in rows:
        r = dict(r)
        if r["entry_type"] == "application":
            stats["total_applications"] += r["cnt"]
            if r["status"] == "interview":
                stats["interviews"] += r["cnt"]
            elif r["status"] == "offer":
                stats["offers"] += r["cnt"]
            elif r["status"] == "rejected":
                stats["rejections"] += r["cnt"]
    total = stats["total_applications"]
    stats["rejection_rate"] = (
        f"{round(stats['rejections'] / total * 100)}%" if total else "0%"
    )
    return stats
