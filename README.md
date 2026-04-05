# Jenax — AI-Powered Daily Planner

Jenax is a local productivity web app that turns your yearly, monthly, and weekly goals into a prioritized daily task list using Google Gemini Flash. Everything runs on localhost and all data stays on your machine in a SQLite database.

![Screenshot placeholder]

## Setup

1. **Get a free Gemini API key**
   - Go to https://aistudio.google.com/apikey
   - Sign in with Google and click "Create API Key"

2. **Configure your key**
   ```
   cp .env.example .env
   # Edit .env and paste your GEMINI_API_KEY
   ```

3. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```

4. **Run**
   ```
   python app.py
   ```
   Open http://localhost:5000

## How to use

1. Add your **yearly goals** first in the sidebar, then break them down into **monthly** and **weekly** sub-goals
2. Each morning, hit **"Generate Today's Plan"** — Gemini will create a focused 5-8 task list based on your goals and recent progress
3. Check off tasks as you complete them throughout the day
4. Review the **Progress** section to track streaks and completion rates over the last 14 days

## Data

All data is stored locally in `jenax.db` (SQLite). No data is sent externally except for goal/task context in the Gemini API prompt, and optionally email content if you connect Gmail (see below).

## Optional: seed example goals

```
python seed_goals.py
```

---

## Gmail Integration (Optional)

Jenax can connect to your Gmail to scan recent emails, summarize your inbox, and extract action items you can add directly to today's task list. This is entirely optional — the app works fine without it. The app never sends emails; it only reads.

### Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a new project (or use an existing one).

2. Go to **APIs & Services → Library**, search for **Gmail API**, and click **Enable**.

3. Go to **APIs & Services → Credentials → Configure Consent Screen**:
   - User type: **External**
   - App name: `jenax`
   - Add your Gmail address as a test user
   - Add scope: `https://www.googleapis.com/auth/gmail.readonly`
   - Save (no need to publish — Testing mode works for personal use)

4. Go to **Credentials → Create Credentials → OAuth Client ID**:
   - Application type: **Web application**
   - Authorized redirect URIs: `http://localhost:5000/auth/gmail/callback`
   - Download the JSON file and save it as `credentials.json` in the jenax folder

5. Add to your `.env`:
   ```
   GOOGLE_CREDENTIALS_PATH=credentials.json
   ```

6. Start Jenax and click **Connect Gmail →** in the sidebar.

### How it works

- Click **Scan Emails** to fetch the last 24 hours of emails
- Gemini summarizes your inbox and extracts action items
- Click **Accept** on any action item to add it directly to today's task list
- Automated and marketing emails are filtered out before anything is sent to Gemini
- Email digests are stored locally for 7 days, then deleted automatically

### Privacy

Your email content is sent to Google's Gemini API for summarization. Emails are not stored on any external server. Only the last 24 hours of emails are read, and you can disconnect at any time from the sidebar.
