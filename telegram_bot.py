import asyncio
import json
import logging
from datetime import date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN

logger = logging.getLogger(__name__)

# Pending settings state: {chat_id: action_string}
_pending_settings: dict[str, str] = {}

PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
MOOD_MAP = {"great": "😊", "good": "🙂", "okay": "😐", "rough": "😕", "bad": "😫"}


# ---------------------------------------------------------------------------
# Bot startup
# ---------------------------------------------------------------------------

def start_bot():
    """Run the Telegram bot in its own thread (called from app.py)."""
    if not TELEGRAM_BOT_TOKEN:
        logger.info("Telegram bot token not configured, skipping bot startup.")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("plan", plan_command))
    application.add_handler(CommandHandler("tasks", tasks_command))
    application.add_handler(CommandHandler("done", done_command))
    application.add_handler(CommandHandler("progress", progress_command))
    application.add_handler(CommandHandler("goals", goals_command))
    application.add_handler(CommandHandler("review", review_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    try:
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Telegram bot stopped: {e}")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import database as db
    chat_id = str(update.effective_chat.id)
    config = db.get_bot_config("telegram")
    if config and config.get("chat_id") == chat_id:
        await update.message.reply_text(
            "You're already connected! Use /help to see commands."
        )
        return
    db.save_bot_config(
        "telegram",
        chat_id=chat_id,
        enabled=1,
        settings_json=json.dumps({
            "morning_plan_time": "07:00",
            "evening_review_time": "21:00",
            "send_morning_plan": True,
            "send_evening_reminder": True,
            "send_email_alerts": True,
            "timezone": "Asia/Kolkata",
        }),
    )
    await update.message.reply_text(
        "Welcome to Jenax! 🎯\n\n"
        "I'll send you your daily plans and reminders.\n"
        "Use /help to see what I can do."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 Jenax Bot Commands:\n\n"
        "/plan — Generate and view today's plan\n"
        "/tasks — See today's tasks with completion status\n"
        "/done <number> — Mark a task as complete (e.g., /done 2)\n"
        "/progress — See your current streak and weekly stats\n"
        "/goals — List your active goals\n"
        "/review — Trigger an end-of-day review\n"
        "/settings — Configure notification times\n"
        "/stop — Pause all notifications\n"
        "/resume — Resume notifications"
    )


async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Generating your plan…")
    try:
        import planner
        result = planner.generate_daily_plan()
    except Exception as e:
        await update.message.reply_text(f"❌ Could not generate plan: {e}")
        return

    if "error" in result:
        await update.message.reply_text(f"❌ {result['error']}")
        return

    import database as db
    tasks = db.get_tasks_for_date(date.today().isoformat())
    text, keyboard = _format_plan(result.get("daily_insight"), tasks)
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import database as db
    tasks = db.get_tasks_for_date(date.today().isoformat())
    text, keyboard = _format_tasks(tasks)
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import database as db
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /done <number>  e.g. /done 2")
        return

    n = int(args[0])
    today = date.today().isoformat()
    tasks = db.get_tasks_for_date(today)
    if n < 1 or n > len(tasks):
        await update.message.reply_text(f"No task #{n}. You have {len(tasks)} task(s) today.")
        return

    task = tasks[n - 1]
    if task["completed"]:
        await update.message.reply_text(f"Task #{n} is already done ✅")
        return

    updated = db.toggle_task(task["id"])
    done_count = sum(1 for t in db.get_tasks_for_date(today) if t["completed"])
    total = len(tasks)
    db.upsert_reflection(today, done_count, total)

    if done_count == total:
        await update.message.reply_text(
            f"🎉 All tasks complete! Amazing work today!"
        )
    else:
        await update.message.reply_text(
            f"✅ Marked '{updated['title']}' as done! ({done_count}/{total} complete today)"
        )


async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import database as db
    data = db.get_progress_data(30)
    streak = data.get("current_streak", 0)
    this_week = data.get("this_week_rate")
    last_week = data.get("last_week_rate")
    best_day = data.get("most_productive_day", "—")
    total = data.get("total_tasks_completed", 0)

    this_pct = f"{round((this_week or 0) * 100)}%" if this_week is not None else "—"
    last_pct = f"{round((last_week or 0) * 100)}%" if last_week is not None else "—"

    await update.message.reply_text(
        f"📊 Your Progress\n\n"
        f"🔥 Current streak: {streak} day{'s' if streak != 1 else ''}\n"
        f"📈 This week: {this_pct} completion\n"
        f"📉 Last week: {last_pct} completion\n"
        f"⭐ Best day: {best_day}\n"
        f"🏆 All-time: {total} tasks completed"
    )


async def goals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import database as db
    goals = db.get_active_goals_flat()
    if not goals:
        await update.message.reply_text("No active goals yet. Add some in the web app!")
        return

    by_level = {"yearly": [], "monthly": [], "weekly": []}
    for g in goals:
        by_level.get(g["level"], []).append(g["title"])

    lines = ["🎯 Your Active Goals\n"]
    labels = {"yearly": "📅 Yearly", "monthly": "📆 Monthly", "weekly": "📋 Weekly"}
    for level in ("yearly", "monthly", "weekly"):
        items = by_level[level]
        if items:
            lines.append(f"{labels[level]}:")
            for t in items:
                lines.append(f"  • {t}")
            lines.append("")

    await update.message.reply_text("\n".join(lines).strip())


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("😊 Great", callback_data="mood_great"),
            InlineKeyboardButton("🙂 Good", callback_data="mood_good"),
            InlineKeyboardButton("😐 Okay", callback_data="mood_okay"),
        ],
        [
            InlineKeyboardButton("😕 Rough", callback_data="mood_rough"),
            InlineKeyboardButton("😫 Bad", callback_data="mood_bad"),
        ],
    ])
    await update.message.reply_text(
        "🌙 How was your day? Select your mood to start the review:",
        reply_markup=keyboard,
    )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import database as db
    config = db.get_bot_config("telegram")
    if not config:
        await update.message.reply_text("Please send /start first to connect your account.")
        return

    settings = json.loads(config.get("settings_json") or "{}")
    morning = settings.get("morning_plan_time", "07:00")
    evening = settings.get("evening_review_time", "21:00")
    email_alerts = "On" if settings.get("send_email_alerts", True) else "Off"
    tz = settings.get("timezone", "UTC")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Change morning time", callback_data="settings_morning")],
        [InlineKeyboardButton("Change evening time", callback_data="settings_evening")],
        [InlineKeyboardButton("Toggle email alerts", callback_data="settings_toggle_email")],
        [InlineKeyboardButton("Change timezone", callback_data="settings_timezone")],
    ])
    await update.message.reply_text(
        f"⚙️ Notification Settings\n\n"
        f"🌅 Morning plan: {morning}\n"
        f"🌙 Evening review: {evening}\n"
        f"📧 Email alerts: {email_alerts}\n"
        f"🕐 Timezone: {tz}\n\n"
        f"Tap to change:",
        reply_markup=keyboard,
    )


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import database as db
    db.update_bot_config("telegram", enabled=0)
    await update.message.reply_text("⏸ Notifications paused. Use /resume to turn them back on.")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import database as db
    db.update_bot_config("telegram", enabled=1)
    await update.message.reply_text("▶️ Notifications resumed!")


# ---------------------------------------------------------------------------
# Callback query handler (button presses)
# ---------------------------------------------------------------------------

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("done_"):
        await _handle_task_done_callback(query, int(data.split("_", 1)[1]))
    elif data.startswith("mood_"):
        await _handle_mood_callback(query, data.split("_", 1)[1])
    elif data.startswith("settings_"):
        await _handle_settings_callback(query, data[len("settings_"):])
    elif data.startswith("email_accept_"):
        await _handle_email_accept(query, int(data.split("_", 2)[2]))
    elif data.startswith("email_dismiss_"):
        await _handle_email_dismiss(query, int(data.split("_", 2)[2]))


async def _handle_task_done_callback(query, task_id):
    import database as db
    today = date.today().isoformat()
    task = db.get_task(task_id)
    if not task or task["completed"]:
        await query.edit_message_text("Task already completed ✅")
        return

    db.toggle_task(task_id)
    tasks = db.get_tasks_for_date(today)
    done_count = sum(1 for t in tasks if t["completed"])
    db.upsert_reflection(today, done_count, len(tasks))

    text, keyboard = _format_tasks(tasks)
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


async def _handle_mood_callback(query, mood):
    import database as db, planner
    today = date.today().isoformat()
    tasks = db.get_tasks_for_date(today)

    await query.edit_message_text(
        f"Mood recorded: {MOOD_MAP.get(mood, mood)} — generating your review…"
    )

    try:
        result = planner.generate_daily_review(notes=None, mood=mood, target_date=today)
    except Exception as e:
        await query.message.reply_text(f"❌ Could not generate review: {e}")
        return

    if "error" in result:
        await query.message.reply_text(f"❌ {result['error']}")
        return

    done = sum(1 for t in tasks if t["completed"])
    total = len(tasks)
    review = result.get("review", {})
    reflection = review.get("reflection", "")
    tomorrow = review.get("tomorrow_suggestions", [])
    encouragement = review.get("encouragement", "")

    lines = [
        f"🌙 End of Day Review\n",
        f"You completed {done} out of {total} tasks today ({round(done/total*100) if total else 0}%).\n",
    ]
    if reflection:
        lines.append(f"📝 {reflection}\n")
    if tomorrow:
        lines.append("💡 Tomorrow's suggestions:")
        for s in tomorrow[:3]:
            lines.append(f"  • {s}")
    if encouragement:
        lines.append(f"\n✨ {encouragement}")

    await query.message.reply_text("\n".join(lines))


async def _handle_settings_callback(query, action):
    import database as db
    chat_id = str(query.message.chat_id)

    if action == "morning":
        _pending_settings[chat_id] = "morning_time"
        await query.edit_message_text(
            "Send me the new morning time (e.g., 06:30 or 08:00):"
        )
    elif action == "evening":
        _pending_settings[chat_id] = "evening_time"
        await query.edit_message_text(
            "Send me the new evening time (e.g., 20:00 or 22:00):"
        )
    elif action == "timezone":
        _pending_settings[chat_id] = "timezone"
        await query.edit_message_text(
            "Send me your timezone (e.g., America/New_York, Europe/London, Asia/Kolkata):"
        )
    elif action == "toggle_email":
        config = db.get_bot_config("telegram")
        settings = json.loads(config.get("settings_json") or "{}")
        settings["send_email_alerts"] = not settings.get("send_email_alerts", True)
        db.update_bot_config("telegram", settings_json=json.dumps(settings))
        status = "On" if settings["send_email_alerts"] else "Off"
        await query.edit_message_text(f"📧 Email alerts toggled: {status}")


async def _handle_email_accept(query, item_id):
    import database as db
    item = db.get_email_action_item(item_id)
    if not item:
        await query.edit_message_text("Action item not found.")
        return
    task = db.create_task(
        title=item["title"],
        description=item.get("description"),
        priority=item.get("priority", "medium"),
        goal_id=None,
        date_str=date.today().isoformat(),
        source="manual",
    )
    db.update_email_action_item(item_id, status="accepted", task_id=task["id"])
    await query.edit_message_text(f"✅ Added to today's tasks: {item['title']}")


async def _handle_email_dismiss(query, item_id):
    import database as db
    db.update_email_action_item(item_id, status="dismissed")
    await query.edit_message_text("Dismissed.")


# ---------------------------------------------------------------------------
# Text message handler (for settings conversations)
# ---------------------------------------------------------------------------

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import database as db, scheduler
    chat_id = str(update.effective_chat.id)
    action = _pending_settings.pop(chat_id, None)
    if not action:
        return

    text = (update.message.text or "").strip()
    config = db.get_bot_config("telegram")
    if not config:
        return
    settings = json.loads(config.get("settings_json") or "{}")

    if action in ("morning_time", "evening_time"):
        # Validate HH:MM format
        parts = text.split(":")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            await update.message.reply_text(
                "Invalid time format. Please use HH:MM (e.g., 07:00)."
            )
            return
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            await update.message.reply_text("Invalid time. Hours 0-23, minutes 0-59.")
            return
        key = "morning_plan_time" if action == "morning_time" else "evening_review_time"
        settings[key] = f"{h:02d}:{m:02d}"
        db.update_bot_config("telegram", settings_json=json.dumps(settings))
        scheduler.update_schedule_times(
            settings.get("morning_plan_time", "07:00"),
            settings.get("evening_review_time", "21:00"),
            settings.get("timezone", "UTC"),
        )
        await update.message.reply_text(f"✅ Updated! New time: {settings[key]}")

    elif action == "timezone":
        import pytz
        try:
            pytz.timezone(text)
        except Exception:
            await update.message.reply_text(
                f"'{text}' is not a valid timezone. Try something like Asia/Kolkata or America/New_York."
            )
            return
        settings["timezone"] = text
        db.update_bot_config("telegram", settings_json=json.dumps(settings))
        scheduler.update_schedule_times(
            settings.get("morning_plan_time", "07:00"),
            settings.get("evening_review_time", "21:00"),
            text,
        )
        await update.message.reply_text(f"✅ Timezone set to: {text}")


# ---------------------------------------------------------------------------
# Scheduler-triggered message functions (sync wrappers)
# ---------------------------------------------------------------------------

def send_morning_plan_sync(chat_id: str):
    """Called by the scheduler to send morning plan."""
    _run_async(send_morning_plan(chat_id))


def send_evening_reminder_sync(chat_id: str):
    """Called by the scheduler to send evening reminder."""
    _run_async(send_evening_reminder(chat_id))


def send_email_alert_sync(chat_id: str, action_items: list):
    """Called by the scheduler to send email alert."""
    _run_async(send_email_alert(chat_id, action_items))


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(coro)
    except Exception as e:
        logger.error(f"Async send error: {e}")
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Async send functions
# ---------------------------------------------------------------------------

async def send_morning_plan(chat_id: str):
    if not TELEGRAM_BOT_TOKEN:
        return
    import database as db, planner
    result = planner.generate_daily_plan()
    if "error" in result:
        return
    tasks = db.get_tasks_for_date(date.today().isoformat())
    text, keyboard = _format_plan(result.get("daily_insight"), tasks)
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    async with bot:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="HTML")


async def send_evening_reminder(chat_id: str):
    if not TELEGRAM_BOT_TOKEN:
        return
    import database as db
    today = date.today().isoformat()
    tasks = db.get_tasks_for_date(today)
    done = sum(1 for t in tasks if t["completed"])
    total = len(tasks)
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    async with bot:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🌙 Time to wrap up! You completed {done}/{total} tasks today.\n"
                f"Use /review to get your daily reflection, or check off any last tasks with /tasks."
            ),
        )


async def send_email_alert(chat_id: str, action_items: list):
    if not TELEGRAM_BOT_TOKEN or not action_items:
        return
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    async with bot:
        for item in action_items[:3]:  # cap at 3 alerts
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("Accept as task", callback_data=f"email_accept_{item.get('id', 0)}"),
                InlineKeyboardButton("Dismiss", callback_data=f"email_dismiss_{item.get('id', 0)}"),
            ]])
            text = (
                f"📧 Urgent email action item:\n"
                f"<b>{_esc(item['title'])}</b>\n"
                f"From: {_esc(item.get('source_sender', ''))}"
                + (f" — Re: {_esc(item.get('source_subject', ''))}" if item.get("source_subject") else "")
            )
            await bot.send_message(
                chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="HTML"
            )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_plan(daily_insight, tasks):
    today_label = date.today().strftime("%a, %b %d").replace(" 0", " ")
    lines = [f"📅 <b>Your Plan for Today ({today_label})</b>\n"]
    if daily_insight:
        lines.append(f'💡 "{_esc(daily_insight)}"\n')

    buttons = []
    for i, t in enumerate(tasks, 1):
        emoji = PRIORITY_EMOJI.get(t.get("priority", "medium"), "🟡")
        status = "✅ " if t["completed"] else f"{emoji} "
        lines.append(f"{i}. {status}{_esc(t['title'])}")
        if not t["completed"]:
            buttons.append(InlineKeyboardButton(f"✓ {i}", callback_data=f"done_{t['id']}"))

    keyboard = None
    if buttons:
        # Split into rows of 5
        rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
        keyboard = InlineKeyboardMarkup(rows)
        lines.append("\nTap a button to mark as done:")

    return "\n".join(lines), keyboard


def _format_tasks(tasks):
    done = sum(1 for t in tasks if t["completed"])
    total = len(tasks)
    lines = [f"📋 <b>Today's Tasks ({done}/{total} done)</b>\n"]

    buttons = []
    for i, t in enumerate(tasks, 1):
        mark = "✅" if t["completed"] else "⬜"
        lines.append(f"{mark} {_esc(t['title'])}")
        if not t["completed"]:
            buttons.append(InlineKeyboardButton(f"✓ {i}", callback_data=f"done_{t['id']}"))

    if not tasks:
        lines.append("No tasks yet. Use /plan to generate today's plan.")

    keyboard = None
    if buttons:
        rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
        keyboard = InlineKeyboardMarkup(rows)
        lines.append("\nUse /done <number> to complete a task")

    return "\n".join(lines), keyboard


def _esc(text: str) -> str:
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
