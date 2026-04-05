# jenax Phase 4 — Telegram Bot, Scheduler & Notifications

## Context

jenax Phases 1-3 are complete and running. The app has:
- Goal hierarchy with CRUD
- AI-generated daily tasks via Gemini Flash
- Task carry-forward, end-of-day reviews, weekly reviews
- Smarter plan generation using review history and patterns
- Gmail integration with OAuth, email scanning, action item extraction
- Progress stats, streaks, trends
- Single-page Flask app, SQLite database, Tailwind CSS frontend

This phase adds three things:
1. **Telegram bot** — sends your morning plan to your phone and lets you interact with tasks from Telegram
2. **Background scheduler** — auto-generates plans and scans emails on a schedule
3. **Browser notifications** — gentle reminders during the day

Do NOT break any existing functionality.

---

## Part 1: Telegram Bot

### What It Does

A Telegram bot that:
- Sends your morning plan at a scheduled time
- Sends end-of-day review reminders
- Lets you check off tasks by tapping buttons
- Lets you ask for a quick status update anytime
- Sends alerts when high-priority email action items come in

### Prerequisites (User Setup)

Document these in README:

1. Open Telegram, search for `@BotFather`
2. Send `/newbot`
3. Choose a name (e.g., "jenax Bot") and username (e.g., "myjenax_bot")
4. BotFather gives you a token like `7123456789:AAHxyz...`
5. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your-bot-token-here
   ```
6. Start the app, then open your bot in Telegram and send `/start`
7. The app registers your chat ID automatically

### Tech Stack Addition

| What | Package | Why |
|------|---------|-----|
| Telegram Bot | `python-telegram-bot` | Mature, async-capable, simple API |

Add to `requirements.txt`:
```
python-telegram-bot==21.*
```

### Project Structure (New Files)

```
jenax/
├── ... (existing files)
├── telegram_bot.py          # Bot setup, command handlers, message sending
└── scheduler.py             # APScheduler-based background task runner
```

### Database Changes

```sql
CREATE TABLE IF NOT EXISTS bot_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT UNIQUE NOT NULL,        -- 'telegram'
    chat_id TEXT,                        -- user's Telegram chat ID
    enabled BOOLEAN DEFAULT 1,
    settings_json TEXT,                  -- JSON blob for preferences
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

The `settings_json` stores user preferences:
```json
{
    "morning_plan_time": "07:00",
    "evening_review_time": "21:00",
    "send_morning_plan": true,
    "send_evening_reminder": true,
    "send_email_alerts": true,
    "timezone": "Asia/Kolkata"
}
```

### Backend: `telegram_bot.py`

#### Bot Initialization

```python
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes
)

# Build the bot application
app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
```

#### Command Handlers

**`/start`**
- Saves the user's `chat_id` to `bot_config` table (service='telegram')
- Replies: "Welcome to jenax! I'll send you your daily plans and reminders. Use /help to see what I can do."
- If already registered, replies: "You're already connected! Use /help to see commands."

**`/help`**
- Replies with:
  ```
  📋 jenax Bot Commands:
  
  /plan — Generate and view today's plan
  /tasks — See today's tasks with completion status
  /done <number> — Mark a task as complete (e.g., /done 2)
  /progress — See your current streak and weekly stats
  /goals — List your active goals
  /review — Trigger an end-of-day review
  /settings — Configure notification times
  /stop — Pause all notifications
  /resume — Resume notifications
  ```

**`/plan`**
- Calls the same logic as `POST /api/generate-plan`
- Formats the result as a Telegram message:
  ```
  📅 Your Plan for Today (Mon, Mar 31)
  
  💡 "Focus on the Python course today — you're 3 days behind schedule."
  
  1. 🔴 Complete Python Chapter 7 exercises (~45min)
  2. 🔴 Reply to Sarah about Q3 budget (~15min)
  3. 🟡 Read 30 pages of Atomic Habits (~40min)
  4. 🟡 Update resume skills section (~30min)
  5. 🟢 Review and organize bookmarks (~15min)
  
  Tap a button to mark as done:
  ```
- Below the message: inline keyboard buttons `[✓ 1] [✓ 2] [✓ 3] [✓ 4] [✓ 5]`

**`/tasks`**
- Fetches today's tasks from the database
- Shows them with completion status:
  ```
  📋 Today's Tasks (3/5 done)
  
  ✅ Complete Python Chapter 7 exercises
  ✅ Reply to Sarah about Q3 budget
  ✅ Read 30 pages of Atomic Habits
  ⬜ Update resume skills section
  ⬜ Review and organize bookmarks
  
  Use /done <number> to complete a task
  ```
- Inline buttons: only show buttons for incomplete tasks

**`/done <number>`**
- Marks the Nth task (in today's task list order) as complete
- Replies: "✅ Marked 'Update resume skills section' as done! (4/5 complete today)"
- If all tasks are done: "🎉 All tasks complete! Amazing work today!"

**`/progress`**
- Calls the same logic as `GET /api/progress`
- Formats as:
  ```
  📊 Your Progress
  
  🔥 Current streak: 5 days
  📈 This week: 73% completion
  📉 Last week: 65% completion
  ⭐ Best day: Tuesdays
  🏆 All-time: 142 tasks completed
  ```

**`/goals`**
- Lists active goals grouped by level:
  ```
  🎯 Your Active Goals
  
  📅 Yearly:
    • Get a software developer job
    • Read 12 books
  
  📆 Monthly:
    • Complete Python course
    • Finish Atomic Habits
  
  📋 Weekly:
    • Finish chapters 5-8
    • Read 50 pages
  ```

**`/review`**
- Triggers the end-of-day review (same as `POST /api/review/daily` but without mood/notes since those are harder to collect via Telegram)
- Sends mood selection first as inline buttons: `[😫] [😐] [🙂] [😊]`
- After mood is selected, generates and sends the review:
  ```
  🌙 End of Day Review
  
  You completed 4 out of 5 tasks today (80%).
  
  📝 "Solid day — you knocked out the Python exercises 
  and stayed on top of email. The resume task slipped 
  again — consider blocking 30 minutes for it first 
  thing tomorrow."
  
  💡 Tomorrow's suggestions:
  • Start with the resume update before anything else
  • You tend to be less productive on Wednesdays — keep it light
  ```

**`/settings`**
- Shows current settings with inline buttons to change them:
  ```
  ⚙️ Notification Settings
  
  🌅 Morning plan: 07:00 AM
  🌙 Evening review: 09:00 PM
  📧 Email alerts: On
  🕐 Timezone: Asia/Kolkata
  
  Tap to change:
  ```
- Inline buttons: `[Change morning time] [Change evening time] [Toggle email alerts]`
- Time changes: bot asks "Send me the new time (e.g., 06:30 or 08:00)" and waits for a text reply
- Timezone: bot asks "Send me your timezone (e.g., America/New_York, Europe/London, Asia/Kolkata)" — validate against pytz/zoneinfo

**`/stop`**
- Sets `enabled = 0` in bot_config
- Replies: "⏸ Notifications paused. Use /resume to turn them back on."

**`/resume`**
- Sets `enabled = 1` in bot_config
- Replies: "▶️ Notifications resumed!"

#### Callback Query Handler (Button Presses)

Handle all inline button presses:
- Task completion buttons (`done_1`, `done_2`, etc.): mark task complete, edit the original message to update the status
- Mood selection (`mood_great`, `mood_good`, etc.): save mood, proceed with review generation
- Settings buttons: handle setting changes

#### Message Sending Functions (called by scheduler)

```python
async def send_morning_plan(chat_id):
    """
    Generate today's plan and send it to the user.
    Same format as /plan command.
    Called by the scheduler at the user's configured morning time.
    """

async def send_evening_reminder(chat_id):
    """
    Send a reminder to review the day.
    Message: "🌙 Time to wrap up! You completed X/Y tasks today. 
    Use /review to get your daily reflection, or just check off 
    any last tasks with /tasks"
    Called by the scheduler at the user's configured evening time.
    """

async def send_email_alert(chat_id, action_items):
    """
    Send a notification when email scanning finds high-priority action items.
    Only sends for HIGH priority items.
    Message: "📧 Urgent email action item:
    [title]
    From: [sender] — Re: [subject]
    
    [Accept as task] [Dismiss]"
    """
```

#### Running the Bot

The bot needs to run alongside Flask. Two approaches:

**Recommended: Run bot in a background thread within the Flask app.**

In `app.py`:
```python
import threading
from telegram_bot import start_bot

# Start bot in background thread when app starts
if TELEGRAM_BOT_TOKEN:
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
```

In `telegram_bot.py`:
```python
def start_bot():
    """
    Initialize and run the Telegram bot using polling.
    This runs in its own thread and doesn't block Flask.
    Uses asyncio.new_event_loop() since it's in a separate thread.
    """
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    # Register all handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("plan", plan_command))
    # ... etc
    app.add_handler(CallbackQueryHandler(button_callback))
    
    app.run_polling()
```

---

## Part 2: Background Scheduler

### What It Does

Runs tasks automatically on a schedule:
- Generate morning plan at the user's configured time
- Send evening review reminder
- Auto-scan emails (if Gmail connected) every few hours
- Clean up old email digests (daily)
- Carry forward yesterday's incomplete tasks (each morning)

### Tech Stack Addition

| What | Package | Why |
|------|---------|-----|
| Scheduler | `APScheduler` | Lightweight, works within Flask process |

Add to `requirements.txt`:
```
apscheduler
```

### Backend: `scheduler.py`

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

scheduler = BackgroundScheduler()

def init_scheduler(app):
    """
    Initialize and start all scheduled jobs.
    Call this once from app.py after all other setup.
    """
    
    # --- Morning routine (runs daily) ---
    # Time is loaded from bot_config settings, default 07:00
    
    scheduler.add_job(
        morning_routine,
        CronTrigger(hour=7, minute=0),  # default, overridden by user settings
        id='morning_routine',
        replace_existing=True,
        misfire_grace_time=3600  # if missed, still run within 1 hour
    )
    
    # --- Evening reminder (runs daily) ---
    scheduler.add_job(
        evening_routine,
        CronTrigger(hour=21, minute=0),
        id='evening_routine',
        replace_existing=True,
        misfire_grace_time=3600
    )
    
    # --- Email scan (every 4 hours during daytime) ---
    scheduler.add_job(
        scheduled_email_scan,
        CronTrigger(hour='8,12,16,20', minute=0),
        id='email_scan',
        replace_existing=True,
        misfire_grace_time=1800
    )
    
    # --- Data cleanup (daily at 3 AM) ---
    scheduler.add_job(
        data_cleanup,
        CronTrigger(hour=3, minute=0),
        id='data_cleanup',
        replace_existing=True
    )
    
    scheduler.start()


def morning_routine():
    """
    Runs each morning:
    1. Carry forward incomplete tasks from yesterday
    2. Generate today's plan using AI
    3. Scan emails for action items (if Gmail connected)
    4. Send morning plan via Telegram (if connected and enabled)
    """

def evening_routine():
    """
    Runs each evening:
    1. Calculate today's completion stats
    2. Send evening reminder via Telegram (if connected and enabled)
    """

def scheduled_email_scan():
    """
    Runs periodically:
    1. Check if Gmail is connected
    2. Fetch recent emails
    3. Process through Gemini
    4. If any HIGH priority action items found, send Telegram alert
    5. Store digest (overwrite today's existing digest)
    """

def data_cleanup():
    """
    Runs nightly:
    1. Delete email_digests older than 7 days
    2. Delete orphaned email_action_items
    """

def update_schedule_times(morning_time, evening_time, timezone):
    """
    Called when user changes settings via Telegram /settings or web UI.
    Reschedules the morning and evening jobs with new times.
    
    morning_time: string like "07:00"
    evening_time: string like "21:00"  
    timezone: string like "Asia/Kolkata"
    """
    hour, minute = map(int, morning_time.split(':'))
    tz = pytz.timezone(timezone)
    
    scheduler.reschedule_job(
        'morning_routine',
        trigger=CronTrigger(hour=hour, minute=minute, timezone=tz)
    )
    # same for evening
```

### Integration with `app.py`

```python
from scheduler import init_scheduler

# After all route definitions and database init:
if __name__ == '__main__':
    init_scheduler(app)
    app.run(debug=True)
```

**Important:** When Flask runs with `debug=True`, it spawns a reloader process which causes the scheduler to start twice. Handle this:
```python
import os
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    init_scheduler(app)
```

---

## Part 3: Browser Notifications

### What It Does

Sends gentle browser notifications during the day:
- "You have 3 tasks remaining today" (mid-day reminder)
- "Time for your evening review" (evening)
- Notification permission is requested on first visit

### Implementation Approach

Use the **Web Notifications API** (built into browsers, no extra packages).

### Frontend Changes

**Notification Permission Request:**

On first page load, after a 5-second delay (don't immediately ask), show a subtle banner at the top of the page:

```
┌─────────────────────────────────────────────────────────┐
│ 🔔 Enable notifications to get task reminders           │
│    during the day.              [Enable] [No thanks]    │
└─────────────────────────────────────────────────────────┘
```

- "Enable" calls `Notification.requestPermission()`
- "No thanks" dismisses the banner and sets `localStorage.jenax_notifications_dismissed = true`
- If already granted, don't show the banner
- If denied at browser level, don't show the banner

**Notification Scheduling (client-side):**

Since the app is a single-page app open in a browser tab, use `setInterval` or `setTimeout` to check task status periodically:

```javascript
// Check every 30 minutes while the page is open
setInterval(async () => {
    if (Notification.permission !== 'granted') return;
    
    const now = new Date();
    const hour = now.getHours();
    
    // Mid-day reminder (between 12:00 and 13:00, once)
    if (hour === 12 && !sessionStorage.midday_notified) {
        const response = await fetch('/api/tasks');
        const tasks = await response.json();
        const remaining = tasks.filter(t => !t.completed).length;
        if (remaining > 0) {
            new Notification('jenax', {
                body: `You have ${remaining} task${remaining > 1 ? 's' : ''} remaining today.`,
                icon: '/static/icon.png',  // optional, create a simple icon
                tag: 'midday-reminder'     // prevents duplicate notifications
            });
            sessionStorage.midday_notified = 'true';
        }
    }
    
    // Evening reminder (between 20:00 and 21:00, once)
    if (hour === 20 && !sessionStorage.evening_notified) {
        new Notification('jenax', {
            body: 'Time to review your day! How did it go?',
            icon: '/static/icon.png',
            tag: 'evening-reminder'
        });
        sessionStorage.evening_notified = 'true';
    }
}, 1800000); // 30 minutes
```

**Note:** Browser notifications only work when the tab is open. This is a known limitation — the Telegram bot is the reliable notification channel. Browser notifications are a nice-to-have supplement.

---

## API Route Additions

### Telegram Config Routes

**`GET /api/config/telegram`**
- Returns: `{ "connected": bool, "chat_id": str or null, "settings": {...} }`

**`PUT /api/config/telegram/settings`**
- Body: `{ "morning_plan_time": "07:00", "evening_review_time": "21:00", ... }`
- Updates settings_json in bot_config
- Calls `scheduler.update_schedule_times()` to reschedule jobs
- Returns: updated settings

### Scheduler Status Route

**`GET /api/scheduler/status`**
- Returns info about scheduled jobs:
  ```json
  {
    "running": true,
    "jobs": [
      {"id": "morning_routine", "next_run": "2025-04-01T07:00:00", "enabled": true},
      {"id": "evening_routine", "next_run": "2025-04-01T21:00:00", "enabled": true},
      {"id": "email_scan", "next_run": "2025-04-01T12:00:00", "enabled": true}
    ]
  }
  ```

**`POST /api/scheduler/trigger/<job_id>`**
- Manually triggers a scheduled job (useful for testing)
- Only allows: morning_routine, evening_routine, email_scan
- Returns: `{ "triggered": "morning_routine" }`

---

## Frontend Changes

### Sidebar: Connections Section Update

Expand the existing "Connections" section in the sidebar:

```
── Connections ──────────────
📧 Gmail: Connected (user@gmail.com)
   [Disconnect]

🤖 Telegram: Connected
   [Configure] [Disconnect]
   
   — or if not connected —

🤖 Telegram: Not connected
   Setup instructions ↗
   
── Automation ──────────────
⏰ Morning plan: 07:00 AM ✓
🌙 Evening review: 09:00 PM ✓
📧 Email scan: Every 4 hours ✓
[Edit Schedule]
```

- "Configure" opens a small settings panel (inline in the sidebar or a modal):
  - Morning plan time (time input)
  - Evening review time (time input)
  - Timezone (dropdown or text input)
  - Toggle switches for: morning plan, evening reminder, email alerts
  - Save button
- "Setup instructions" links to the README section or shows a modal with BotFather setup steps
- Since Telegram connection happens FROM Telegram (user sends /start to the bot), the web UI just shows whether a chat_id is registered

### Settings Modal for Automation

When user clicks "Edit Schedule":

```
┌─────────────────────────────────────────────┐
│ ⏰ Automation Settings                       │
│                                              │
│ Morning Plan Generation                      │
│ [Toggle ON] at [07:00] ▼                    │
│ Automatically generate your daily plan       │
│                                              │
│ Evening Review Reminder                      │
│ [Toggle ON] at [21:00] ▼                    │
│ Reminder to review your day                  │
│                                              │
│ Email Scanning                               │
│ [Toggle ON] every [4 hours] ▼               │
│ Scan Gmail for action items                  │
│ (Only when Gmail is connected)               │
│                                              │
│ Timezone                                     │
│ [Asia/Kolkata          ] ▼                  │
│                                              │
│                    [Save] [Cancel]            │
└─────────────────────────────────────────────┘
```

- Time inputs: use HTML `<input type="time">`
- Email scan frequency: dropdown with options `[Every 2 hours, Every 4 hours, Every 8 hours, Twice a day, Once a day]`
- Timezone: text input with datalist of common timezones, or just a text field that validates against pytz
- Save calls `PUT /api/config/telegram/settings` and updates the scheduler

### Notification Permission Banner

A slim banner at the very top of the page (above everything else):

```
┌─────────────────────────────────────────────────────────────┐
│ 🔔 Get task reminders in your browser  [Enable] [Dismiss]  │
└─────────────────────────────────────────────────────────────┘
```

- Only shows if: notifications not granted AND not previously dismissed
- Subtle styling: light blue/gray background, small text
- Dismisses permanently (localStorage flag)

---

## Error Handling

### Telegram Bot
- If `TELEGRAM_BOT_TOKEN` is not set: bot doesn't start, no error, just skip. Log a message: "Telegram bot token not configured, skipping bot startup."
- If bot fails to start (invalid token): catch the error, log it, don't crash Flask
- If sending a message fails (user blocked bot, network error): catch, log, continue. Don't retry for notifications — they're not critical.
- If the user hasn't sent /start yet (no chat_id): scheduled messages simply don't send. No error.

### Scheduler
- If a scheduled job fails: APScheduler logs the error by default. Configure it to NOT crash on job errors:
  ```python
  scheduler = BackgroundScheduler(job_defaults={'misfire_grace_time': 3600})
  ```
- If Flask restarts (debug mode reload): scheduler restarts cleanly due to `replace_existing=True`
- If the PC was asleep during a scheduled time: `misfire_grace_time` allows the job to run late (within 1 hour for plans, 30 min for email scans)

### Browser Notifications
- If permission denied: silently stop trying. Don't nag the user.
- If `Notification` API not available (e.g., HTTP without HTTPS): hide the banner entirely. Check with `if ('Notification' in window)`.

---

## Updated `.env.example`

```
# LLM
GEMINI_API_KEY=your-gemini-api-key

# Gmail Integration (optional)
GOOGLE_CREDENTIALS_PATH=credentials.json

# Telegram Bot (optional)
TELEGRAM_BOT_TOKEN=your-telegram-bot-token

# Scheduler timezone (optional, default: UTC)
DEFAULT_TIMEZONE=Asia/Kolkata
```

---

## README Additions

### Telegram Bot (Optional)

Get your daily plan delivered to Telegram and manage tasks from your phone.

**Setup:**

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow the prompts to create a bot
3. Copy the token BotFather gives you
4. Add it to your `.env` file: `TELEGRAM_BOT_TOKEN=your-token`
5. Restart jenax
6. Open your new bot in Telegram and send `/start`
7. That's it — you'll start receiving your morning plan automatically

**Commands:**
- `/plan` — Generate today's plan
- `/tasks` — View today's tasks
- `/done 3` — Mark task #3 as done
- `/progress` — See your stats
- `/review` — End-of-day review
- `/settings` — Change notification times
- `/stop` / `/resume` — Pause/resume notifications

### Automation

jenax can run tasks automatically:
- **Morning plan** — generated at 7:00 AM (configurable)
- **Evening reminder** — sent at 9:00 PM (configurable)
- **Email scanning** — every 4 hours (configurable, requires Gmail connection)

Configure these in the app's sidebar under "Automation", or via the Telegram `/settings` command.

---

## Implementation Order

Build in this exact sequence:

1. **`scheduler.py`** — set up APScheduler with placeholder jobs. Integrate with `app.py`. Verify jobs run on schedule using simple print/log statements.

2. **`telegram_bot.py` — core setup** — bot initialization, `/start` and `/help` commands, chat_id storage. Verify the bot responds in Telegram.

3. **`telegram_bot.py` — task commands** — `/plan`, `/tasks`, `/done`, `/progress`, `/goals` commands. Verify each works correctly.

4. **`telegram_bot.py` — review commands** — `/review` with mood selection via inline buttons. Verify the flow works.

5. **`telegram_bot.py` — settings** — `/settings`, `/stop`, `/resume` commands. Verify settings are saved and schedule updates.

6. **Connect scheduler to bot** — wire `morning_routine` to generate plan + send via Telegram. Wire `evening_routine` to send reminder. Wire `scheduled_email_scan` to scan + alert on high-priority items. Test by manually triggering via the API.

7. **API routes** — add `/api/config/telegram`, `/api/scheduler/status`, `/api/scheduler/trigger`.

8. **Frontend: sidebar updates** — Telegram connection status, automation settings display.

9. **Frontend: settings modal** — schedule configuration UI.

10. **Frontend: browser notifications** — permission banner, midday and evening notification logic.

11. **Polish** — test all edge cases: bot not configured, PC sleep/wake, timezone changes, debug mode double-start, notification permissions denied.

## Important Notes

- The Telegram bot runs in a daemon thread — it must not block Flask and must not crash the main process.
- All scheduled jobs must be idempotent — running them twice should not create duplicate tasks or send duplicate messages.
- Use `replace_existing=True` on all jobs so restarts don't create duplicate schedulers.
- The scheduler and bot are both OPTIONAL. If tokens are not configured, the app works exactly as before. No errors, no warnings in the UI — just the connection section shows "Not connected".
- Test the threading carefully. Flask and the Telegram bot share the SQLite database — use proper connection handling (one connection per operation, not a shared global connection). SQLite handles concurrent reads fine but writes need care.
- For the Telegram inline keyboards, always include a `callback_data` string that encodes the action and target (e.g., `"done_3"` for completing task 3, `"mood_good"` for mood selection).
- `python-telegram-bot` v21 is fully async. Since it runs in its own thread with its own event loop, this is fine. But database calls from bot handlers should use synchronous SQLite (not async).
- Browser notifications are a progressive enhancement. They should never block or delay page rendering. All notification logic goes at the end of the script tag.