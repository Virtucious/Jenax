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

**Single-module Flask app** — no blueprints, no application factory. All routes live in `app.py`, which calls into `database.py` and `planner.py` directly.

### Data flow for AI plan generation
`POST /api/generate-plan` → `planner.generate_daily_plan()` → pulls active goals + 7-day task history from SQLite → builds prompt → calls Gemini API → parses JSON response → bulk-inserts tasks via `database.create_task()` → upserts today's reflection stats.

Raw LLM prompt/response pairs are logged to `logs/YYYY-MM-DD.txt` for debugging.

### Database layer (`database.py`)
All SQL is written by hand using `sqlite3` (stdlib). `get_connection()` sets `row_factory = sqlite3.Row` so rows can be accessed by column name and converted to `dict`. Foreign keys are enabled per-connection (`PRAGMA foreign_keys = ON`).

Three tables: `goals` (self-referential tree via `parent_id`), `daily_tasks`, `daily_reflections`. Goals cascade-delete to children; tasks set `goal_id = NULL` on goal delete.

`get_all_goals()` returns the full tree as nested dicts with a `children` key — this is the shape the frontend sidebar expects. `get_active_goals_flat()` is the flat list used for prompt building.

### Frontend (`templates/index.html`)
Single HTML file — all JS is inline at the bottom, no build step, no framework. Uses Tailwind CDN and vanilla `fetch()`. State is held in two module-level JS arrays: `goalsFlat` (for dropdowns) and `goalsTree` (for rendering the sidebar). The goal modal doubles as both create and edit form, toggled by whether `modal-goal-id` is populated.

### LLM model
Currently uses `gemini-1.5-flash`. Do not change to `gemini-2.0-flash` — the free-tier API key has quota 0 for that model.
