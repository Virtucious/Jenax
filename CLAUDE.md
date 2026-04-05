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

**Single-module Flask app** — no blueprints, no application factory. All routes live in `app.py`, which calls into `database.py`, `planner.py`, `gmail_client.py`, and `email_processor.py` directly.

### Data flow for AI plan generation
`POST /api/generate-plan` → `planner.generate_daily_plan()` → pulls active goals + 7-day task history + pending email action items from SQLite → builds prompt → calls Gemini API → parses JSON response → bulk-inserts tasks via `database.create_task()` → upserts today's reflection stats.

Raw LLM prompt/response pairs are logged to `logs/YYYY-MM-DD.txt` for debugging.

### Data flow for Gmail / email digest
`GET /auth/gmail/connect` → redirects to Google OAuth consent → callback at `GET /auth/gmail/callback` → token stored in `oauth_tokens` table.
`POST /api/email/scan` → `gmail_client.fetch_recent_emails()` → `email_processor.process_emails()` → results saved to `email_digests` + `email_action_items` tables → returned to frontend.
`PATCH /api/email/action/<id>/accept` → creates a `daily_tasks` row with `source='email'` → links task id back to action item.

### Database layer (`database.py`)
All SQL is written by hand using `sqlite3` (stdlib). `get_connection()` sets `row_factory = sqlite3.Row` so rows can be accessed by column name and converted to `dict`. Foreign keys are enabled per-connection (`PRAGMA foreign_keys = ON`).

Seven tables: `goals`, `daily_tasks`, `daily_reflections`, `weekly_reviews`, `oauth_tokens`, `email_digests`, `email_action_items`. Goals cascade-delete to children; tasks set `goal_id = NULL` on goal delete. Email action items cascade-delete with their digest.

On startup, `init_db()` also deletes `email_digests` (and their action items) older than 7 days.

`get_all_goals()` returns the full tree as nested dicts with a `children` key — this is the shape the frontend sidebar expects. `get_active_goals_flat()` is the flat list used for prompt building.

### Gmail integration (`gmail_client.py`, `email_processor.py`)
`gmail_client.py` owns all OAuth logic and raw email fetching. Tokens are stored as JSON in the `oauth_tokens` table — no `token.json` file on disk. `get_gmail_service()` transparently refreshes expired tokens; if refresh fails it deletes the token and returns `None` (caller must prompt re-auth).

`email_processor.py` takes the list of email dicts from `gmail_client` and sends them to Gemini with a structured prompt, returning `{summary, action_items, categories}`.

`GOOGLE_CREDENTIALS_PATH` in `.env` must point to the OAuth credentials JSON downloaded from Google Cloud Console. If the file is absent, the sidebar shows a setup prompt rather than crashing.

### Frontend (`templates/index.html`)
Single HTML file — all JS is inline at the bottom, no build step, no framework. Uses Tailwind CDN and vanilla `fetch()`. State is held in two module-level JS arrays: `goalsFlat` (for dropdowns) and `goalsTree` (for rendering the sidebar). The goal modal doubles as both create and edit form, toggled by whether `modal-goal-id` is populated.

Gmail connection status is checked on every page load via `loadGmailStatus()`. The Email Digest section is hidden until Gmail is connected. The first-ever scan triggers a privacy notice modal; acceptance is stored in `localStorage` (`jenax_email_notice_accepted`).

### LLM model
Currently uses `gemini-2.5-flash` in both `planner.py` and `email_processor.py`. Do not change to a model with quota 0 on your free-tier key.
