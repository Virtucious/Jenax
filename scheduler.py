import json
import logging
import os
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(job_defaults={"misfire_grace_time": 3600})


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_scheduler(app):
    """Start scheduler only in the main Flask process (avoids double-start in debug mode).

    app.debug is False at call time (set later by app.run), so we rely solely on
    WERKZEUG_RUN_MAIN: present means we're in the reloader child → safe to start.
    Absent means either the reloader parent (skip) or a non-debug run (start).
    We check the DEBUG constant passed through the env to distinguish these.
    """
    werkzeug_main = os.environ.get("WERKZEUG_RUN_MAIN")
    # If WERKZEUG_RUN_MAIN is set at all, we're under the reloader.
    # Only start in the child (value == 'true'), not the parent (not set).
    # If not under reloader at all, always start.
    if werkzeug_main is None or werkzeug_main == "true":
        _start_scheduler()


def _start_scheduler():
    from config import DEFAULT_TIMEZONE
    try:
        tz = pytz.timezone(DEFAULT_TIMEZONE)
    except Exception:
        tz = pytz.utc

    # Load user-configured times from DB if available
    morning_hour, morning_minute = 7, 0
    evening_hour, evening_minute = 21, 0
    try:
        import database as db
        config = db.get_bot_config("telegram")
        if config and config.get("settings_json"):
            settings = json.loads(config["settings_json"])
            mt = settings.get("morning_plan_time", "07:00").split(":")
            et = settings.get("evening_review_time", "21:00").split(":")
            morning_hour, morning_minute = int(mt[0]), int(mt[1])
            evening_hour, evening_minute = int(et[0]), int(et[1])
            tz_str = settings.get("timezone", DEFAULT_TIMEZONE)
            try:
                tz = pytz.timezone(tz_str)
            except Exception:
                pass
    except Exception:
        pass

    scheduler.add_job(
        morning_routine,
        CronTrigger(hour=morning_hour, minute=morning_minute, timezone=tz),
        id="morning_routine",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        evening_routine,
        CronTrigger(hour=evening_hour, minute=evening_minute, timezone=tz),
        id="evening_routine",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        scheduled_email_scan,
        CronTrigger(hour="8,12,16,20", minute=0, timezone=tz),
        id="email_scan",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    scheduler.add_job(
        data_cleanup,
        CronTrigger(hour=3, minute=0, timezone=tz),
        id="data_cleanup",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started.")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def morning_routine():
    """Carry forward tasks, generate plan, scan emails, send Telegram morning plan."""
    try:
        import database as db
        db.carry_forward_tasks()
        logger.info("morning_routine: carry-forward done.")
    except Exception as e:
        logger.error(f"morning_routine carry_forward error: {e}")

    try:
        import database as db
        db.check_habit_progression()
        logger.info("morning_routine: habit progression checked.")
    except Exception as e:
        logger.error(f"morning_routine habit progression error: {e}")

    try:
        import planner
        planner.generate_daily_plan()
        logger.info("morning_routine: daily plan generated.")
    except Exception as e:
        logger.error(f"morning_routine generate_plan error: {e}")

    try:
        _run_email_scan_and_alert(hours=24)
    except Exception as e:
        logger.error(f"morning_routine email scan error: {e}")

    try:
        _send_morning_telegram()
    except Exception as e:
        logger.error(f"morning_routine telegram error: {e}")


def evening_routine():
    """Send evening reminder via Telegram."""
    try:
        _send_evening_telegram()
    except Exception as e:
        logger.error(f"evening_routine telegram error: {e}")


def scheduled_email_scan():
    """Scan emails since last check and alert on high-priority items."""
    try:
        _run_email_scan_and_alert(hours=4)
    except Exception as e:
        logger.error(f"scheduled_email_scan error: {e}")


def data_cleanup():
    """Delete email digests older than 7 days."""
    try:
        import database as db
        conn = db.get_connection()
        with conn:
            conn.execute(
                """DELETE FROM email_action_items WHERE digest_id IN (
                    SELECT id FROM email_digests WHERE date < date('now', '-7 days')
                )"""
            )
            conn.execute("DELETE FROM email_digests WHERE date < date('now', '-7 days')")
        conn.close()
        logger.info("data_cleanup: old digests removed.")
    except Exception as e:
        logger.error(f"data_cleanup error: {e}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_email_scan_and_alert(hours=4):
    import gmail_client, email_processor, database as db

    status = gmail_client.is_connected()
    if not status["connected"]:
        return

    emails = gmail_client.fetch_recent_emails(hours=hours, max_results=50)
    if not emails:
        return

    result = email_processor.process_emails(emails)
    today = date.today().isoformat()
    digest_id = db.upsert_email_digest(
        today, len(emails), result.get("summary"), json.dumps(emails)
    )
    db.save_email_action_items(digest_id, result.get("action_items", []))

    high_priority = [i for i in result.get("action_items", []) if i.get("priority") == "high"]
    if high_priority:
        _send_email_alert_telegram(high_priority)


def _send_morning_telegram():
    import database as db
    config = db.get_bot_config("telegram")
    if not _telegram_enabled(config):
        return
    settings = json.loads(config.get("settings_json") or "{}")
    if not settings.get("send_morning_plan", True):
        return
    from telegram_bot import send_morning_plan_sync
    send_morning_plan_sync(config["chat_id"])


def _send_evening_telegram():
    import database as db
    config = db.get_bot_config("telegram")
    if not _telegram_enabled(config):
        return
    settings = json.loads(config.get("settings_json") or "{}")
    if not settings.get("send_evening_reminder", True):
        return
    from telegram_bot import send_evening_reminder_sync
    send_evening_reminder_sync(config["chat_id"])


def _send_email_alert_telegram(action_items):
    import database as db
    config = db.get_bot_config("telegram")
    if not _telegram_enabled(config):
        return
    settings = json.loads(config.get("settings_json") or "{}")
    if not settings.get("send_email_alerts", True):
        return
    from telegram_bot import send_email_alert_sync
    send_email_alert_sync(config["chat_id"], action_items)


def _telegram_enabled(config):
    return config and config.get("chat_id") and config.get("enabled")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_schedule_times(morning_time, evening_time, timezone):
    """Reschedule morning/evening jobs after user changes settings."""
    if not scheduler.running:
        return
    try:
        tz = pytz.timezone(timezone)
        h, m = map(int, morning_time.split(":"))
        scheduler.reschedule_job(
            "morning_routine",
            trigger=CronTrigger(hour=h, minute=m, timezone=tz),
        )
        he, me = map(int, evening_time.split(":"))
        scheduler.reschedule_job(
            "evening_routine",
            trigger=CronTrigger(hour=he, minute=me, timezone=tz),
        )
        logger.info(f"Schedule updated: morning={morning_time}, evening={evening_time}, tz={timezone}")
    except Exception as e:
        logger.error(f"update_schedule_times error: {e}")


def get_status():
    """Return scheduler status dict for the API."""
    if not scheduler.running:
        return {"running": False, "jobs": []}
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id": job.id,
            "next_run": next_run.isoformat() if next_run else None,
            "enabled": True,
        })
    return {"running": True, "jobs": jobs}


def trigger_job(job_id):
    """Manually trigger a scheduled job by id."""
    allowed = {"morning_routine", "evening_routine", "email_scan"}
    if job_id not in allowed:
        return False
    job_map = {
        "morning_routine": morning_routine,
        "evening_routine": evening_routine,
        "email_scan": scheduled_email_scan,
    }
    try:
        job_map[job_id]()
        return True
    except Exception as e:
        logger.error(f"trigger_job({job_id}) error: {e}")
        return False
