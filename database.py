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
        """)

    # Schema migrations — safe to re-run
    migrations = [
        "ALTER TABLE daily_tasks ADD COLUMN carried_from DATE DEFAULT NULL",
        "ALTER TABLE daily_reflections ADD COLUMN mood TEXT CHECK(mood IN ('great', 'good', 'okay', 'rough', 'bad')) DEFAULT NULL",
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
                carried_from=None):
    if date_str is None:
        date_str = date.today().isoformat()
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO daily_tasks
               (title, description, priority, goal_id, date, source, estimated_minutes, carried_from)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, priority, goal_id, date_str, source, estimated_minutes, carried_from),
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
        row = conn.execute("SELECT completed FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
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
