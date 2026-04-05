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

All data is stored locally in `jenax.db` (SQLite). No data is ever sent anywhere except for the goal/task context included in the Gemini API prompt.

## Optional: seed example goals

```
python seed_goals.py
```
