# Jenax Phase 2 — Smarter Daily Loop

## Context

Jenax Phase 1 is complete and running. It has:
- Flask backend with SQLite database
- Goal CRUD (yearly → monthly → weekly hierarchy)
- AI-generated daily task lists via Gemini Flash
- Task completion toggling
- Basic 14-day progress grid
- Single-page HTML frontend with Tailwind CSS

This spec adds features that make the system learn from your behavior and adapt. Do NOT break any existing functionality. All additions should integrate cleanly with the existing codebase.

---

## Feature 1: Task Carry-Forward

### What It Does
When you open the app on a new day, incomplete tasks from yesterday are not lost. They appear as "carried forward" candidates. The user can accept or dismiss each one before (or after) generating a new plan.

### Database Changes

Add a column to `daily_tasks`:
```sql
ALTER TABLE daily_tasks ADD COLUMN carried_from DATE DEFAULT NULL;
```

If `carried_from` is not null, it means this task was carried forward from that date.

### Backend Changes

**New route: `POST /api/tasks/carry-forward`**
- Looks at yesterday's incomplete tasks (where `completed = 0` and `date = date('now', '-1 day')`)
- For each incomplete task, creates a new copy in today's date with `carried_from` set to the original date
- Does NOT duplicate if a carry-forward for that task already exists today (check by matching title + carried_from)
- Returns the list of carried-forward tasks

**Modify `GET /api/tasks?date=YYYY-MM-DD`**
- Include the `carried_from` field in the response
- Add a boolean field `is_carried` (true if carried_from is not null) for easier frontend handling

### Frontend Changes

- When the page loads and today has no tasks yet, show a banner at the top of the task area:
  > "You have X incomplete tasks from yesterday. [Review them →]"
- Clicking the banner calls `POST /api/tasks/carry-forward` and shows the carried tasks with a subtle visual indicator (e.g., a small "↩ carried" badge next to the title, muted color)
- Each carried task has a dismiss button (X) that deletes it
- Carried tasks appear above newly generated tasks, separated by a subtle divider

---

## Feature 2: End-of-Day Review

### What It Does
A button that triggers an AI-powered reflection on your day. It looks at what you completed, what you didn't, and gives you a short reflection + suggestions for tomorrow.

### Database Changes

The `daily_reflections` table already exists. We'll use it more fully now:

```sql
-- If the table doesn't already have these columns, add them:
-- ai_summary TEXT        (already exists)
-- notes TEXT             (already exists — this is for user's own notes)
-- mood TEXT              (add if not present)
ALTER TABLE daily_reflections ADD COLUMN mood TEXT CHECK(mood IN ('great', 'good', 'okay', 'rough', 'bad')) DEFAULT NULL;
```

### Backend Changes

**New route: `POST /api/review/daily`**
- Accepts optional body: `{ "notes": "...", "mood": "good" }`
- Gathers today's data:
  - All tasks for today (completed and incomplete)
  - The goals those tasks link to
  - Yesterday's reflection (if any) for continuity
  - Completion stats for the last 7 days
- Sends to Gemini with the review prompt (see below)
- Saves the response + user notes + mood into `daily_reflections`
- Returns the full reflection

**New route: `GET /api/review/daily?date=YYYY-MM-DD`**
- Returns the stored reflection for that date (or null if none exists)

### LLM Prompt for Daily Review

```
You are a thoughtful productivity coach reviewing someone's day. Be honest but encouraging. Don't sugarcoat, but don't be harsh.

## Today's Results
Date: {date}
Tasks completed: {completed_count}/{total_count}

### Completed:
{for each completed task: "✓ [title] (priority: X, linked to goal: Y)"}

### Not completed:
{for each incomplete task: "✗ [title] (priority: X, linked to goal: Y)"}

### User's mood: {mood or "not specified"}
### User's notes: {notes or "none"}

### Yesterday's reflection (for context):
{yesterday's ai_summary or "No review yesterday"}

### 7-Day completion trend:
{for each of last 7 days: "date: X/Y tasks completed"}

## Instructions
1. In 2-3 sentences, reflect on how the day went. Reference specific tasks.
2. If high-priority tasks were skipped, gently note why that matters.
3. Note any patterns you see in the 7-day trend (improving? declining? inconsistent?)
4. Suggest 1-2 specific adjustments for tomorrow.

Respond ONLY with valid JSON:
{
  "reflection": "Your 2-3 sentence reflection on the day",
  "patterns_noticed": "Any patterns from the 7-day trend, or null",
  "tomorrow_suggestions": ["suggestion 1", "suggestion 2"],
  "encouragement": "One short encouraging sentence"
}
```

### Frontend Changes

Add a new section at the bottom of today's dashboard, above the progress grid:

**"End of Day" section**
- Only shows after 5 PM local time (use JS `new Date().getHours()`)... actually, always show it but make it more prominent after 5 PM
- Contains:
  - A mood selector: 5 emoji-style buttons in a row (😫 rough → 😐 okay → 🙂 good → 😊 great). Highlight the selected one.
  - A small textarea: "Any notes about today?" (optional, 2-3 lines)
  - "Review My Day" button
- After clicking:
  - Show spinner while waiting
  - Display the AI reflection in a styled card:
    - Main reflection text (larger font)
    - Patterns noticed (if any, in a subtle callout box)
    - Tomorrow's suggestions as a small list
    - Encouragement as a closing line (slightly italic, accent color)
- If a review already exists for today, show it instead of the input form. Add a "Redo Review" button that regenerates.

---

## Feature 3: Weekly Review

### What It Does
Every week (or on demand), generates a comprehensive summary of the week: what progressed, what stalled, patterns, and a recommended focus for next week.

### Database Changes

```sql
CREATE TABLE IF NOT EXISTS weekly_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    total_tasks INTEGER,
    completed_tasks INTEGER,
    completion_rate REAL,
    goals_progressed TEXT,   -- JSON array of goal IDs that had tasks completed
    goals_neglected TEXT,    -- JSON array of goal IDs with no activity
    ai_review TEXT,          -- Full AI-generated review
    focus_areas TEXT,        -- JSON array of suggested focus areas for next week
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(week_start)
);
```

### Backend Changes

**New route: `POST /api/review/weekly`**
- Accepts optional `{ "week_start": "YYYY-MM-DD" }` — defaults to the Monday of the current week
- Gathers data for that Mon-Sun period:
  - All tasks, their completion status, linked goals
  - Daily reflections for each day that week
  - All active goals and which ones had tasks completed vs not
  - Previous week's review (for trend comparison)
- Sends to Gemini (see prompt below)
- Saves into `weekly_reviews`
- Returns the full review

**New route: `GET /api/review/weekly?week_start=YYYY-MM-DD`**
- Returns stored weekly review, or null

**New route: `GET /api/reviews/weekly/list`**
- Returns list of all weekly reviews (id, week_start, week_end, completion_rate) for a history view

### LLM Prompt for Weekly Review

```
You are a strategic productivity coach doing a weekly review. Be analytical and actionable.

## Week: {week_start} to {week_end}

### Daily Breakdown:
{for each day of the week:
  "Day (date): completed X/Y tasks
   - Completed: [task titles]
   - Missed: [task titles]
   - Mood: {mood or 'not recorded'}
   - Daily reflection summary: {ai_summary or 'none'}
"}

### Goal Activity This Week:
{for each active goal:
  "Goal: [title] (level: yearly/monthly/weekly)
   Tasks completed this week: X
   Tasks missed: Y
   Status: active/on-track/falling-behind
"}

### Goals With ZERO Activity This Week:
{list of goal titles that had no tasks completed}

### Previous Week's Summary (for trend):
{last week's ai_review or "No previous review"}

## Instructions:
1. Summarize the week in 3-4 sentences. Be specific about what went well and what didn't.
2. Identify the top 2-3 goals that progressed most.
3. Flag any goals that are being consistently neglected (this week AND last week).
4. Note behavioral patterns: does the user complete more early in the week? Do they skip certain types of tasks?
5. Recommend 2-3 focus areas for next week, prioritizing neglected goals.

Respond ONLY with valid JSON:
{
  "week_summary": "3-4 sentence summary",
  "wins": ["specific win 1", "specific win 2"],
  "concerns": ["concern 1 with specific goal reference", "concern 2"],
  "patterns": "Behavioral pattern observation or null",
  "next_week_focus": [
    {"goal_id": <id>, "goal_title": "...", "suggestion": "specific action to take"},
    {"goal_id": <id>, "goal_title": "...", "suggestion": "specific action to take"}
  ],
  "overall_trend": "improving|stable|declining"
}
```

### Frontend Changes

Add a "Weekly Review" tab/section accessible from the sidebar or a tab in the main content area:

**Option A (recommended): Add a tab bar above the main content**
- Two tabs: "Today" (default, what currently exists) and "Weekly Review"
- Clicking "Weekly Review" shows the weekly view

**Weekly Review View:**
- At the top: a week selector (← Previous Week | "Mar 24 - Mar 30" | Next Week →)
- "Generate Weekly Review" button (only if no review exists for selected week)
- When a review exists, display it as a structured card:
  - **Week Summary** — the main text, prominent
  - **Wins** — shown with ✓ icons, green accent
  - **Concerns** — shown with ⚠ icons, amber accent
  - **Patterns** — in a callout/info box if present
  - **Next Week's Focus** — as actionable cards with the linked goal name
  - **Overall Trend** — a badge: green "Improving" / gray "Stable" / red "Declining"
- Below the AI review: a mini calendar/heatmap of the week (Mon-Sun, 7 cells) showing daily completion rates (same color coding as the 14-day grid)

---

## Feature 4: Smarter Plan Generation (Upgrade Existing)

### What It Does
Upgrade the existing `POST /api/generate-plan` to use review data for better planning.

### Backend Changes

**Modify the plan generation prompt in `planner.py`:**

Enhance the existing prompt to include:
- Yesterday's reflection (if exists) — especially the `tomorrow_suggestions`
- Last weekly review's `next_week_focus` areas
- Carried-forward tasks from yesterday
- Pattern data: which days of the week the user typically completes more/fewer tasks

The new prompt additions (append to existing prompt context):

```
## Yesterday's Review
{yesterday's ai_summary, including tomorrow_suggestions}

## This Week's Focus Areas (from weekly review)
{next_week_focus items from most recent weekly review}

## Carried Forward from Yesterday
{list of tasks carried forward, if any — the AI should consider keeping or dropping these}

## Day-of-Week Pattern
{e.g., "The user typically completes 80% of tasks on Mondays but only 50% on Fridays. Today is Wednesday (usually ~65%)."}

Additional rules:
- If yesterday's review suggested specific actions for today, incorporate them.
- If weekly focus areas mention a neglected goal, include at least one task for it.
- If a task has been carried forward 3+ times, flag it in the daily_insight — either it should be broken into smaller pieces or reconsidered.
- Adjust the number of tasks based on day-of-week patterns (fewer tasks on historically low-completion days).
```

### Frontend Changes
- No major UI changes needed — the existing "Generate Today's Plan" button now just produces smarter results
- If a task has been carried forward multiple times, show a small warning icon with tooltip: "This task has been carried forward X times"

---

## Feature 5: Streak & Stats Enhancement

### What It Does
Make the progress section more motivating and informative.

### Backend Changes

**Modify `GET /api/progress`** to return additional data:
```json
{
  "daily_completion": [...],          // existing 14-day data
  "current_streak": 5,               // consecutive days with >50% completion
  "longest_streak": 12,              // all-time best
  "this_week_rate": 0.73,            // completion rate this week
  "last_week_rate": 0.65,            // completion rate last week
  "trend": "improving",             // improving/stable/declining
  "most_productive_day": "Tuesday",  // day with highest avg completion
  "total_tasks_completed": 142,      // all-time count
  "goals_completed": 3               // number of goals marked complete
}
```

### Frontend Changes

Replace or upgrade the existing progress section:

- **Streak display**: Large number with flame emoji: "🔥 5 day streak" (or "Start a streak today!" if 0)
- **This week vs last week**: Simple comparison — "This week: 73% ↑ (last week: 65%)"
- **Best day badge**: "You're most productive on Tuesdays"
- **All-time counter**: Small stat at the bottom: "142 tasks completed across 3 finished goals"
- Keep the existing 14-day heatmap grid but extend it to 30 days, scrollable horizontally if needed

---

## Implementation Order

Build these in this exact sequence, testing each before moving on:

1. **Task carry-forward** (Feature 1) — database migration, new route, frontend banner
2. **End-of-day review** (Feature 2) — new routes, LLM prompt, review UI section
3. **Weekly review** (Feature 3) — new table, routes, prompts, tab UI
4. **Smarter plan generation** (Feature 4) — prompt upgrades only, no new UI
5. **Stats enhancement** (Feature 5) — backend stats calculation, frontend polish

## Important Notes

- Run any `ALTER TABLE` or `CREATE TABLE` statements in `database.py` initialization so they run automatically on startup. Use `IF NOT EXISTS` and wrap ALTERs in try/except so they don't fail on re-runs.
- All new LLM calls go through the same Gemini setup in `planner.py` (or a shared module). Don't create a separate API client.
- Keep the same error handling pattern: if Gemini fails, return a clear error to the frontend. Never crash.
- All new frontend sections go in the same `index.html` file. Do not create new HTML files.
- Preserve the existing design language — same colors, same card styles, same button styles. New sections should look like they were always part of the app.
- Test the carry-forward logic carefully around midnight edge cases. Use `date('now')` consistently in SQLite.
- Weekly review calculations should handle partial weeks (e.g., if it's Wednesday, the current week only has 3 days of data).