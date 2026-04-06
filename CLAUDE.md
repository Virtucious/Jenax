# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
python app.py          # runs Flask dev server at http://localhost:5000
```

Requires a `.env` file with `GEMINI_API_KEY` (copy from `.env.example`). The SQLite database (`jenax.db`) is created automatically on first run.

To seed example goals:
```bash
python seed_goals.py
```

## Architecture

**Single-module Flask app** — no blueprints, no application factory. All routes live in `app.py`, which calls into `database.py`, `planner.py`, `gmail_client.py`, `email_processor.py`, `scheduler.py`, and the `agents/` package directly.

### LLM model
All agents use `gemini-3-flash-preview` via the `google-genai` SDK. The model is set in `agents/base.py` (`_MODEL`). Do not change to a model with quota 0 on your free-tier key.

---

### Data flow for AI plan generation

`POST /api/generate-plan` → `planner.generate_daily_plan()` → instantiates `Orchestrator` → runs four agents in sequence → merges outputs → bulk-inserts tasks via `database.create_task()` → upserts today's reflection stats.

If the Orchestrator fails, `planner.py` falls back to a single legacy Gemini call.

Raw LLM prompt/response pairs are stored in the `agent_logs` table (not flat files — the `logs/` directory is only used by the legacy path).

### Agent pipeline (`agents/`)

All agents inherit from `BaseAgent` (`agents/base.py`), which handles:
- `build_context()` → gather DB data
- `build_prompt(context, extra_input)` → compose prompt string
- Gemini call with one JSON-parse retry
- Logging every run to `agent_logs` table (agent name, trigger type, raw prompt/response, parsed output, duration, success)

The four agents and their roles:

| Agent | File | Role |
|-------|------|------|
| `AccountabilityAgent` | `agents/accountability_agent.py` | Detects behavioral patterns, goal avoidance, streaks; produces typed insights (nudge/warning/critical) |
| `EmailAgent` | `agents/email_agent.py` | Triages raw email dicts; extracts action items relevant to active goals |
| `ResearchAgent` | `agents/research_agent.py` | Generates bite-sized learning tasks for goals matching learning keywords |
| `PlannerAgent` | `agents/planner_agent.py` | Synthesizes all agent outputs into the final prioritised task list |

`Orchestrator` (`agents/orchestrator.py`) coordinates them in order: Accountability → Email (if Gmail connected) → Research (if learning goals exist) → Planner. It short-circuits accountability if a result exists in `agent_logs` within the last 6 hours.

### Data flow for Gmail / email digest

`GET /auth/gmail/connect` → redirects to Google OAuth consent → callback at `GET /auth/gmail/callback` → token stored in `oauth_tokens` table.
`POST /api/email/scan` → `gmail_client.fetch_recent_emails()` → `email_processor.process_emails()` → results saved to `email_digests` + `email_action_items` tables → returned to frontend.
`PATCH /api/email/action/<id>/accept` → creates a `daily_tasks` row with `source='email'` → links task id back to action item.

### Data flow for Telegram bot

`telegram_bot.start_bot()` is called from `app.py` in a background thread. It uses `python-telegram-bot` with polling. On `/start`, the bot saves a `bot_configs` row with `platform='telegram'`, the user's `chat_id`, and default notification settings. Settings (morning time, evening time, timezone, toggles) are stored as JSON in `bot_configs.settings_json`. Changes via `/settings` call `scheduler.update_schedule_times()` to reschedule live APScheduler jobs.

### Scheduler (`scheduler.py`)

APScheduler (`BackgroundScheduler`) starts in `init_scheduler()`. It avoids double-start under Werkzeug's reloader by checking `WERKZEUG_RUN_MAIN`. Four jobs:

| Job | Schedule | Action |
|-----|----------|--------|
| `morning_routine` | 7:00am (configurable) | carry-forward tasks → generate plan → email scan → Telegram morning message |
| `evening_routine` | 9:00pm (configurable) | Telegram wrap-up reminder |
| `email_scan` | 8am, 12pm, 4pm, 8pm | scan last 4h of email; alert on high-priority items |
| `data_cleanup` | 3:00am daily | delete `email_digests` older than 7 days |

Times and timezone come from `bot_configs.settings_json` at startup and can be updated live via `update_schedule_times()`.

### Database layer (`database.py`)

All SQL is written by hand using `sqlite3` (stdlib). `get_connection()` sets `row_factory = sqlite3.Row` so rows can be accessed by column name and converted to `dict`. Foreign keys are enabled per-connection (`PRAGMA foreign_keys = ON`).

Eleven tables:

| Table | Notes |
|-------|-------|
| `goals` | Hierarchical (yearly/monthly/weekly); cascade-delete to children |
| `daily_tasks` | Tasks with date, priority, energy_level, source, is_carried, goal_id (set NULL on goal delete) |
| `daily_reflections` | Per-day completion stats and mood |
| `weekly_reviews` | Weekly summaries |
| `oauth_tokens` | Gmail OAuth tokens as JSON (no `token.json` on disk) |
| `email_digests` | Processed email summaries; 7-day TTL enforced at startup and by nightly job |
| `email_action_items` | Action items extracted from digests; cascade-delete with digest |
| `learning_resources` | Books, courses, videos etc. with `completed_units`/`total_units` progress |
| `accountability_insights` | AI-detected patterns with `valid_until` expiry date |
| `bot_configs` | Platform-keyed bot settings (Telegram chat_id, notification times, timezone) |
| `agent_logs` | Raw agent runs: prompt, response, parsed output, duration, success flag |

`get_all_goals()` returns the full tree as nested dicts with a `children` key — this is the shape the frontend sidebar expects. `get_active_goals_flat()` is the flat list used for prompt building.

`init_db()` runs on every startup; it creates missing tables and deletes stale email digests.

### Gmail integration (`gmail_client.py`, `email_processor.py`)

`gmail_client.py` owns all OAuth logic and raw email fetching. Tokens are stored as JSON in the `oauth_tokens` table — no `token.json` file on disk. `get_gmail_service()` transparently refreshes expired tokens; if refresh fails it deletes the token and returns `None` (caller must prompt re-auth).

`email_processor.py` takes the list of email dicts from `gmail_client` and sends them to Gemini with a structured prompt, returning `{summary, action_items, categories}`. It is the legacy single-agent path; the multi-agent pipeline uses `EmailAgent` instead.

`GOOGLE_CREDENTIALS_PATH` in `.env` must point to the OAuth credentials JSON downloaded from Google Cloud Console. If the file is absent, the sidebar shows a setup prompt rather than crashing.

### Frontend (`templates/index.html`)

Single HTML file — all JS is inline at the bottom, no build step, no framework. Uses Tailwind CDN and vanilla `fetch()`. State is held in two module-level JS arrays: `goalsFlat` (for dropdowns) and `goalsTree` (for rendering the sidebar). The goal modal doubles as both create and edit form, toggled by whether `modal-goal-id` is populated.

Gmail connection status is checked on every page load via `loadGmailStatus()`. The Email Digest section is hidden until Gmail is connected. The first-ever scan triggers a privacy notice modal; acceptance is stored in `localStorage` (`jenax_email_notice_accepted`).

### Configuration (`config.py`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | — | Gemini API key |
| `GOOGLE_CREDENTIALS_PATH` | No | `credentials.json` | Gmail OAuth credentials JSON path |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram bot token from BotFather |
| `DEFAULT_TIMEZONE` | No | `UTC` | Scheduler and bot notification timezone |
| `DATABASE_PATH` | No | `jenax.db` | SQLite database path |
