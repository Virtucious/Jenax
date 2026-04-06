# Jenax — AI-Powered Daily Planner

Jenax is a local productivity web app that turns your yearly, monthly, and weekly goals into a prioritized daily task list using Google Gemini. Everything runs on localhost and all data stays on your machine in a SQLite database.

---

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Onboarding Guide](#onboarding-guide)
- [Optional Integrations](#optional-integrations)
  - [Gmail Integration](#gmail-integration)
  - [Telegram Bot](#telegram-bot)
- [Configuration Reference](#configuration-reference)
- [Architecture Overview](#architecture-overview)

---

## Features

### Core Planning
- **Hierarchical goals** — define yearly goals, break them into monthly sub-goals, then weekly targets
- **AI daily plan generation** — Gemini builds a focused 5–8 task list each morning based on your goals and recent task history
- **Task management** — check off tasks throughout the day; carry-forward for incomplete tasks is automatic
- **Daily review** — end-of-day AI reflection with mood tracking and suggestions for tomorrow
- **Progress dashboard** — streak tracking, weekly/14-day completion rates, best day of week stats

### Multi-Agent AI Pipeline
Plan generation runs through four coordinated AI agents:

| Agent | Role |
|-------|------|
| **Accountability Agent** | Detects behavioral patterns, goal avoidance, and streaks — provides warnings and celebration nudges |
| **Email Agent** | Triages your Gmail inbox and extracts high-priority action items to include in the plan |
| **Research Agent** | Tracks learning goals, suggests bite-sized study tasks, monitors course/book progress |
| **Planner Agent** | Synthesizes all agent outputs into your final daily task list with workload assessment |

### Learning Corner
- Track books, courses, tutorials, articles, and videos
- Log progress by chapter, page, module, or custom unit
- AI-generated study tasks matched to your learning resources

### Accountability Insights
- AI-detected patterns (goal avoidance, productivity trends, day-of-week habits)
- Insights persist across days and are surfaced in your daily plan
- Severity levels: info, nudge, warning, critical

### Automated Scheduling
- Morning routine automatically carries forward tasks, generates the daily plan, scans email, and sends a Telegram message
- Evening routine sends a wrap-up reminder via Telegram
- Email scans run at 8am, 12pm, 4pm, and 8pm (configurable)
- Nightly cleanup removes email digests older than 7 days

### Gmail Integration (optional)
- Reads the last 24 hours of emails
- AI summarizes your inbox and extracts action items
- Accept items directly into today's task list
- Automated and marketing emails are filtered before reaching the AI
- High-priority items trigger real-time Telegram alerts

### Telegram Bot (optional)
Control everything from your phone:

| Command | Description |
|---------|-------------|
| `/plan` | Generate and view today's plan |
| `/tasks` | See today's tasks with completion status |
| `/done <n>` | Mark task #n as complete |
| `/progress` | Streak, weekly stats, all-time totals |
| `/goals` | List active goals by level |
| `/review` | Trigger end-of-day review with mood selection |
| `/resources` | List learning resources with progress bars |
| `/progress_update <n> <units>` | Update progress on a learning resource |
| `/insights` | View active accountability insights |
| `/settings` | Configure notification times and timezone |
| `/stop` / `/resume` | Pause or resume all notifications |

---

## Quick Start

### Prerequisites
- Python 3.10+
- A free [Gemini API key](https://aistudio.google.com/apikey)

### Install

```bash
git clone <repo-url>
cd jenax
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Open .env and set GEMINI_API_KEY=your_key_here
```

### Run

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000).

---

## Onboarding Guide

Follow these steps your first time using Jenax.

### Step 1 — Set your yearly goals

In the sidebar, click **+ Add Goal** and set the level to **Yearly**. Add 2–4 goals that represent what you want to achieve this year.

Example: `Learn Python`, `Run a 5K`, `Ship a side project`

### Step 2 — Break goals into monthly targets

Add **Monthly** goals as children of your yearly goals. These should represent what you'll focus on this month.

Example under "Learn Python": `Complete the FastAPI course`

### Step 3 — Add weekly focus items

Add **Weekly** goals under your monthly ones. These are concrete targets for this week.

Example: `Finish FastAPI chapters 1–4`, `Build a sample CRUD API`

### Step 4 — Generate your first plan

Click **Generate Today's Plan** in the main area. Gemini will produce a focused task list based on everything you've entered. This takes a few seconds.

### Step 5 — Work through your tasks

Check off tasks as you complete them. The progress bar updates in real time.

### Step 6 — Do your evening review

At the end of the day, click **Review** to reflect on what went well, log your mood, and get AI-generated suggestions for tomorrow.

### Step 7 (optional) — Seed example goals

If you want to explore the app with pre-filled data before adding your own goals:

```bash
python seed_goals.py
```

---

## Optional Integrations

### Gmail Integration

Jenax can read your Gmail to surface action items in your daily plan. It never sends email.

#### Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.

2. Enable the **Gmail API**: APIs & Services → Library → Gmail API → Enable.

3. Configure the OAuth consent screen: APIs & Services → OAuth Consent Screen
   - User type: **External**
   - App name: `jenax`
   - Add your Gmail address as a test user
   - Add scope: `https://www.googleapis.com/auth/gmail.readonly`

4. Create credentials: Credentials → Create Credentials → OAuth Client ID
   - Application type: **Web application**
   - Authorized redirect URI: `http://localhost:5000/auth/gmail/callback`
   - Download the JSON and save it as `credentials.json` in the project folder

5. Add to `.env`:
   ```
   GOOGLE_CREDENTIALS_PATH=credentials.json
   ```

6. Start Jenax and click **Connect Gmail** in the sidebar. Complete the OAuth flow.

#### How it works

- Click **Scan Emails** to fetch the last 24 hours
- Gemini summarizes your inbox and lists action items
- Click **Accept** on an action item to add it to today's tasks
- Digests are stored locally for 7 days, then deleted automatically

---

### Telegram Bot

Get your daily plan and manage tasks from Telegram.

#### Setup

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, follow the prompts, and copy your bot token
3. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_token_here
   DEFAULT_TIMEZONE=Asia/Kolkata   # or your timezone
   ```
4. Restart Jenax — the bot starts automatically alongside the web app
5. Open your bot in Telegram and send `/start`

The bot will now send you:
- A morning plan at 7:00am (your timezone)
- An evening reminder at 9:00pm
- Alerts for high-priority email action items

You can change notification times via `/settings` in the bot.

---

## Configuration Reference

All configuration goes in `.env`. Copy `.env.example` to get started.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | — | Gemini API key from Google AI Studio |
| `GOOGLE_CREDENTIALS_PATH` | No | `credentials.json` | Path to Gmail OAuth credentials JSON |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram bot token from BotFather |
| `DEFAULT_TIMEZONE` | No | `UTC` | Timezone for scheduler and bot notifications |
| `DATABASE_PATH` | No | `jenax.db` | Path to the SQLite database file |

---

## Architecture Overview

**Single-module Flask app** — no blueprints. All routes live in `app.py`, which calls into `database.py`, `planner.py`, `gmail_client.py`, `email_processor.py`, `scheduler.py`, and the `agents/` package.

```
app.py              — Flask routes and startup
database.py         — All SQL (sqlite3, no ORM)
planner.py          — Plan generation entry point; falls back to legacy single-agent if orchestrator fails
scheduler.py        — APScheduler jobs (morning, evening, email scan, cleanup)
telegram_bot.py     — Telegram bot commands and inline keyboard handlers
gmail_client.py     — Gmail OAuth and email fetching
email_processor.py  — Email summarisation via Gemini
config.py           — Env var loading
agents/
  base.py               — BaseAgent (prompt building, Gemini call, response parsing, logging)
  orchestrator.py       — Coordinates agents; merges outputs into final plan dict
  planner_agent.py      — Produces prioritised task list
  email_agent.py        — Email triage and action item extraction
  research_agent.py     — Learning task generation and resource tracking
  accountability_agent.py — Behavioral pattern detection and insights
templates/
  index.html        — Single-page frontend (Tailwind CDN, vanilla JS, no build step)
logs/               — Raw LLM prompt/response pairs (YYYY-MM-DD.txt)
jenax.db            — SQLite database (created automatically)
```

### Database tables

| Table | Purpose |
|-------|---------|
| `goals` | Hierarchical goals (yearly / monthly / weekly) |
| `daily_tasks` | Tasks with date, priority, completion, energy level, source |
| `daily_reflections` | Per-day completion stats and mood |
| `weekly_reviews` | Weekly summaries |
| `oauth_tokens` | Gmail OAuth tokens (no file on disk) |
| `email_digests` | Processed email summaries (7-day TTL) |
| `email_action_items` | Action items extracted from email digests |
| `learning_resources` | Books, courses, and other tracked resources |
| `accountability_insights` | AI-detected patterns with expiry date |
| `bot_configs` | Telegram bot settings (chat ID, notification times, timezone) |
| `agent_logs` | Raw agent prompt/response pairs and metadata |

All data is stored locally. The only external calls are to the Gemini API (for plan generation and email processing) and optionally the Gmail API (for reading your inbox).
