# jenax Phase 3 — Gmail Integration

## Context

jenax Phase 1 and 2 are complete and running. The app has:
- Goal hierarchy (yearly → monthly → weekly) with full CRUD
- AI-generated daily task lists via Gemini Flash
- Task carry-forward from previous days
- End-of-day reviews with mood tracking
- Weekly reviews with pattern analysis
- Smarter plan generation using review history
- Progress stats, streaks, and trends
- Single-page Flask app, SQLite database, Tailwind CSS frontend

This phase adds **read-only Gmail integration** — the app scans your recent emails, summarizes them, extracts action items, and suggests them as tasks. The app will NEVER send emails, only read.

Do NOT break any existing functionality. All additions integrate cleanly with the existing codebase.

---

## How It Works (User's Perspective)

1. User clicks "Connect Gmail" in the app → redirected to Google's OAuth consent screen
2. User grants READ-ONLY access to their Gmail
3. App stores the OAuth token locally (in the SQLite database)
4. A new "Email Digest" section appears on the dashboard
5. User clicks "Scan Emails" → app fetches last 24hrs of emails → sends them to Gemini for summarization and action item extraction
6. Action items appear as suggested tasks — user can accept (adds to today's tasks) or dismiss
7. The daily plan generation also considers pending email action items

---

## Prerequisites (User Must Do Before This Works)

These steps happen OUTSIDE the app. Document them clearly in the README.

### Step 1: Create a Google Cloud Project (free)
1. Go to https://console.cloud.google.com/
2. Create a new project (name it "jenax" or anything)
3. Enable the **Gmail API**: go to APIs & Services → Library → search "Gmail API" → Enable

### Step 2: Create OAuth Credentials
1. Go to APIs & Services → Credentials → Create Credentials → OAuth Client ID
2. If prompted, configure the OAuth consent screen:
   - User type: **External**
   - App name: "jenax"
   - Scopes: add `https://www.googleapis.com/auth/gmail.readonly`
   - Test users: add your own Gmail address
   - No need to publish — "Testing" mode is fine for personal use
3. Application type: **Web application**
4. Authorized redirect URIs: add `http://localhost:5000/auth/gmail/callback`
5. Download the credentials JSON — save it as `credentials.json` in the jenax project root

### Step 3: Add to `.env`
```
# Existing
GEMINI_API_KEY=your-key

# New — path to the downloaded Google credentials file
GOOGLE_CREDENTIALS_PATH=credentials.json
```

---

## Tech Stack Additions

| What | Package | Why |
|------|---------|-----|
| Google Auth | `google-auth`, `google-auth-oauthlib` | OAuth2 flow |
| Gmail API | `google-api-python-client` | Read emails |

Add to `requirements.txt`:
```
google-auth
google-auth-oauthlib
google-api-python-client
```

---

## Project Structure (New Files Only)

```
jenax/
├── ... (existing files)
├── gmail_client.py         # OAuth flow + email fetching
├── email_processor.py      # LLM-based email summarization & action extraction
└── credentials.json        # User downloads this from Google Cloud (gitignored)
```

Add `credentials.json` and `token.json` to `.gitignore`.

---

## Database Changes

### Table: `email_digests`
```sql
CREATE TABLE IF NOT EXISTS email_digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL DEFAULT (date('now')),
    emails_scanned INTEGER DEFAULT 0,
    ai_summary TEXT,
    raw_emails_json TEXT,       -- stored for re-processing if needed
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `email_action_items`
```sql
CREATE TABLE IF NOT EXISTS email_action_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_id INTEGER REFERENCES email_digests(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT CHECK(priority IN ('high', 'medium', 'low')),
    source_subject TEXT,        -- subject line of the email this came from
    source_sender TEXT,         -- sender of the email
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'dismissed')),
    task_id INTEGER REFERENCES daily_tasks(id) ON DELETE SET NULL,  -- linked task if accepted
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `oauth_tokens`
```sql
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT UNIQUE NOT NULL,     -- 'gmail' for now, extensible later
    token_json TEXT NOT NULL,         -- serialized token object
    email TEXT,                       -- user's email address for display
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Backend: `gmail_client.py`

This module handles OAuth and raw email fetching. It does NOT do any AI processing.

### Functions

```python
# --- OAuth Flow ---

def get_auth_url():
    """
    Build and return the Google OAuth authorization URL.
    Uses credentials.json, requests gmail.readonly scope.
    Redirect URI: http://localhost:5000/auth/gmail/callback
    Returns: (auth_url, state)
    """

def handle_callback(auth_code):
    """
    Exchange the authorization code for tokens.
    Save the token to the oauth_tokens table (service='gmail').
    Also fetch and store the user's email address for display.
    Returns: user's email address
    """

def get_gmail_service():
    """
    Load token from oauth_tokens table.
    If token is expired, refresh it and update the database.
    If no token exists or refresh fails, return None (user needs to re-auth).
    Returns: gmail API service object or None
    """

def is_connected():
    """
    Check if a valid Gmail token exists.
    Returns: { "connected": bool, "email": str or None }
    """

def disconnect():
    """
    Delete the token from oauth_tokens table.
    Revoke the token with Google if possible.
    """

# --- Email Fetching ---

def fetch_recent_emails(hours=24, max_results=50):
    """
    Fetch emails from the last N hours.
    Uses Gmail API's messages.list with a query like:
        "newer_than:1d" or "after:{epoch_timestamp}"
    
    For each message:
    1. Get message metadata (subject, from, to, date)
    2. Get the plain text body (prefer text/plain, fall back to text/html stripped of tags)
    3. Skip emails from noreply addresses, newsletters, and automated notifications
       (filter by sender patterns: noreply@, no-reply@, notifications@, mailer-daemon@)
    4. Truncate each email body to 1000 characters max (we only need enough for summarization)
    
    Returns: list of dicts:
    [
        {
            "id": "msg_id",
            "subject": "...",
            "sender": "Name <email>",
            "date": "ISO datetime",
            "snippet": "first 200 chars",
            "body": "truncated body text (max 1000 chars)",
            "labels": ["INBOX", "UNREAD", ...]
        }
    ]
    """
```

### Important Implementation Notes

- Use `google.oauth2.credentials.Credentials` and `google_auth_oauthlib.flow.Flow`
- Store tokens as JSON in the database, not as files (cleaner, no `token.json` file needed)
- Handle token refresh transparently — if a refresh fails, mark as disconnected
- The Gmail API returns email bodies as base64url encoded — decode properly
- For HTML-only emails, strip tags to get plain text (use a simple regex or `html.parser`)
- Rate limiting: Gmail API free tier allows 250 quota units per user per second — fetching 50 emails is well within limits

---

## Backend: `email_processor.py`

This module sends emails to Gemini for summarization and action item extraction.

### Function

```python
def process_emails(emails):
    """
    Takes the list of email dicts from gmail_client.fetch_recent_emails().
    Sends them to Gemini for analysis.
    Returns: {
        "summary": "...",
        "action_items": [
            {
                "title": "...",
                "description": "...",
                "priority": "high|medium|low",
                "source_subject": "...",
                "source_sender": "..."
            }
        ],
        "categories": {
            "needs_reply": 3,
            "informational": 8,
            "action_required": 2,
            "can_ignore": 5
        }
    }
    """
```

### LLM Prompt for Email Processing

```
You are an executive assistant reviewing someone's recent emails. Your job is to:
1. Provide a brief summary of the inbox
2. Extract concrete action items that the user needs to do
3. Categorize the emails

## Recent Emails (last 24 hours)

{for each email:
"---
From: {sender}
Subject: {subject}
Date: {date}
Body: {body (truncated)}
---"
}

## Instructions

1. **Summary**: Write a 2-4 sentence overview of the inbox. Mention any urgent items first. Group related emails together (e.g., "3 emails about Project X").

2. **Action Items**: Extract tasks the user needs to actually DO. Rules:
   - Only include items that require the user's action (reply, review, complete, decide, attend)
   - Do NOT include informational emails, newsletters, or notifications
   - Each action item should be a concrete, completable task
   - Set priority based on urgency and importance:
     - high: has a deadline soon, someone is waiting, or it's from a boss/important contact
     - medium: needs to be done but not urgent
     - low: nice to do, optional, or low-stakes

3. **Categories**: Count how many emails fall into each bucket:
   - needs_reply: someone asked a question or is waiting for a response
   - action_required: requires the user to do something other than reply
   - informational: FYI, updates, newsletters, no action needed
   - can_ignore: automated notifications, marketing, spam-adjacent

Respond ONLY with valid JSON:
{
  "summary": "2-4 sentence inbox summary",
  "action_items": [
    {
      "title": "Short action-oriented task title",
      "description": "1-2 sentences on what exactly to do and why",
      "priority": "high|medium|low",
      "source_subject": "Original email subject line",
      "source_sender": "Sender name"
    }
  ],
  "categories": {
    "needs_reply": <number>,
    "informational": <number>,
    "action_required": <number>,
    "can_ignore": <number>
  }
}

If there are no action items, return an empty array for action_items. 
If there are no emails, return a summary saying "No new emails in the last 24 hours."
```

### Privacy Consideration
- Email bodies are sent to Gemini's API for processing. The user should be aware of this.
- Show a one-time notice in the UI when they first connect: "Your email content will be sent to Google's Gemini API for summarization. Emails are not stored on any external server."
- Store `raw_emails_json` locally in the database for re-processing — but only keep the last 7 days. Add a cleanup step that deletes email_digests older than 7 days on app startup.

---

## API Routes

### OAuth Routes

**`GET /auth/gmail/status`**
- Returns: `{ "connected": true/false, "email": "user@gmail.com" or null }`

**`GET /auth/gmail/connect`**
- Generates the OAuth URL via `gmail_client.get_auth_url()`
- Redirects the user's browser to Google's consent screen

**`GET /auth/gmail/callback`**
- Google redirects here after the user grants access
- Calls `gmail_client.handle_callback(code)`
- Redirects back to `/?gmail=connected` (the frontend can show a success toast)

**`POST /auth/gmail/disconnect`**
- Calls `gmail_client.disconnect()`
- Returns: `{ "success": true }`

### Email Routes

**`POST /api/email/scan`**
- Calls `gmail_client.fetch_recent_emails(hours=24)`
- If not connected, returns `{ "error": "Gmail not connected", "code": "NOT_CONNECTED" }`
- Passes emails to `email_processor.process_emails()`
- Saves results to `email_digests` and `email_action_items` tables
- Returns the full digest + action items

**`GET /api/email/digest?date=YYYY-MM-DD`**
- Returns the stored digest for that date, including action items
- Default: today

**`PATCH /api/email/action/<id>/accept`**
- Changes action item status to "accepted"
- Creates a corresponding task in `daily_tasks` for today:
  - title and description from the action item
  - priority from the action item
  - source = 'email' (add 'email' to the source CHECK constraint: `CHECK(source IN ('ai', 'manual', 'email'))`)
  - goal_id = null (email tasks don't link to goals)
- Stores the new task_id in the action item's `task_id` field
- Returns the created task

**`PATCH /api/email/action/<id>/dismiss`**
- Changes action item status to "dismissed"
- Returns: `{ "success": true }`

---

## Frontend Changes

### Sidebar Addition: Gmail Connection

At the bottom of the sidebar (below the goal tree), add a "Connections" section:

```
── Connections ──────────────
📧 Gmail: Connected (user@gmail.com)
   [Disconnect]

   — or if not connected —

📧 Gmail: Not connected
   [Connect Gmail →]
```

- "Connect Gmail" opens `/auth/gmail/connect` in the same window (not a popup — the OAuth flow will redirect back)
- "Disconnect" calls `POST /auth/gmail/disconnect` with a confirmation prompt
- Check connection status on page load via `GET /auth/gmail/status`

### Main Content: Email Digest Section

Add a new section between the "Daily Insight" card and the task list. Only show this section if Gmail is connected.

**Layout:**

```
┌─────────────────────────────────────────────┐
│ 📧 Email Digest                [Scan Emails]│
│                                              │
│ (Before scanning — empty state)              │
│ "Scan your recent emails to find action      │
│  items and get a summary."                   │
│                                              │
│ (After scanning)                             │
│ ┌─────────────────────────────────────────┐  │
│ │ Summary                                 │  │
│ │ "You received 18 emails in the last     │  │
│ │  24 hours. 3 need replies, 2 require    │  │
│ │  action..."                             │  │
│ │                                         │  │
│ │  📩 Needs reply: 3  │  ⚡ Action: 2    │  │
│ │  📄 Info: 8         │  🗑 Ignore: 5    │  │
│ └─────────────────────────────────────────┘  │
│                                              │
│ Action Items (2)                             │
│ ┌─────────────────────────────────────────┐  │
│ │ 🔴 Reply to Sarah about Q3 budget       │  │
│ │    From: Sarah Chen — Re: Q3 Planning   │  │
│ │    "Sarah asked for your input on..."   │  │
│ │                     [Accept] [Dismiss]  │  │
│ ├─────────────────────────────────────────┤  │
│ │ 🟡 Review PR #482 before EOD            │  │
│ │    From: DevBot — PR ready for review   │  │
│ │    "A pull request needs your review.." │  │
│ │                     [Accept] [Dismiss]  │  │
│ └─────────────────────────────────────────┘  │
│                                              │
│ (After all items accepted/dismissed)         │
│ "All caught up! ✓"                          │
└─────────────────────────────────────────────┘
```

**Behavior:**
- "Scan Emails" button shows a spinner while working. Disable the button while scanning.
- If a scan was already done today, show the stored results. Add a "Rescan" button (smaller, secondary style).
- Action items show priority as colored dots (high=red, medium=yellow, low=green).
- "Accept" button: calls the accept endpoint, the action item card transitions out with a subtle animation, and the new task appears in the task list below.
- "Dismiss" button: card transitions out.
- When all items are handled, show "All caught up! ✓"
- Category counts (needs_reply, action, info, ignore) shown as a small 2x2 grid with icons.

### Privacy Notice (One-Time)

On the first ever email scan, show a modal:

```
┌─────────────────────────────────────────────┐
│ 📧 Email Processing Notice                  │
│                                              │
│ To summarize your emails and extract action  │
│ items, your email content will be sent to    │
│ Google's Gemini API for processing.          │
│                                              │
│ • Emails are processed in real-time and not  │
│   stored on any external server              │
│ • Only the last 24 hours of emails are read  │
│ • Automated/marketing emails are filtered    │
│   out before processing                      │
│ • You can disconnect Gmail at any time       │
│                                              │
│              [I Understand, Continue]         │
│              [Cancel]                         │
└─────────────────────────────────────────────┘
```

Store a flag in localStorage (`jenax_email_notice_accepted = true`) so it only shows once.

### Integration with Plan Generation

When generating the daily plan (`POST /api/generate-plan`), if there are pending (not yet accepted or dismissed) email action items from today's digest, include them in the planning prompt:

Add this section to the existing plan generation prompt:
```
## Pending Email Action Items
The user's inbox has these unhandled action items:
{for each pending action item:
  "- [priority] {title} (from: {source_sender}, re: {source_subject})"
}
Consider incorporating high-priority email actions into today's task list.
Do NOT duplicate them — just factor them into your prioritization.
```

---

## Error Handling

### OAuth Errors
- If `credentials.json` is missing: show a friendly message in the sidebar connection area — "To connect Gmail, follow the setup guide in README.md" (not a crash)
- If token refresh fails: automatically set status to disconnected, show "Gmail disconnected — please reconnect"
- If user denies consent: redirect back to `/?gmail=denied`, show a toast "Gmail access was not granted"

### API Errors
- If Gmail API returns 403 (insufficient permissions): prompt user to reconnect
- If Gmail API returns 429 (rate limit): show "Too many requests, try again in a minute"
- If Gemini fails during email processing: show "Could not process emails — try again" but still store the raw emails so user can retry without re-fetching

### Edge Cases
- No emails in last 24 hours: show a summary saying "No new emails" with 0 action items
- All emails are automated/filtered out: show "X emails scanned, all were automated notifications. No action items."
- Very long email threads: truncate body at 1000 chars per email, max 50 emails per scan
- Multiple scans in one day: each scan replaces the previous digest for today (upsert on date)

---

## Data Cleanup

In `database.py` initialization (runs on app startup):
```python
# Clean up email digests older than 7 days
DELETE FROM email_action_items WHERE digest_id IN (
    SELECT id FROM email_digests WHERE date < date('now', '-7 days')
);
DELETE FROM email_digests WHERE date < date('now', '-7 days');
```

This keeps the database lean since email data has a short shelf life.

---

## Database Migration

Add 'email' to the source CHECK constraint on `daily_tasks`. Since SQLite doesn't support ALTER COLUMN, handle this carefully:

Option A (recommended): If you originally created the table with CHECK constraints, you'll need to recreate it. BUT if the existing app works without strict CHECK enforcement (SQLite doesn't enforce CHECK by default unless compiled with SQLITE_ENABLE_CHECK_CONSTRAINTS), you can just insert 'email' source values and they'll work.

Option B: If CHECKs are enforced, recreate the table:
```sql
-- In database.py, during initialization, check if 'email' source is supported
-- Try inserting a test row — if it fails, recreate the table with the updated constraint
-- This is a one-time migration
```

Prefer Option A — just insert with source='email' and handle gracefully. Document that the CHECK was expanded.

---

## Security Notes

- `credentials.json` contains your Google Cloud client secret — add to `.gitignore`
- OAuth tokens in the database contain refresh tokens — the SQLite file should not be shared
- All communication with Google APIs uses HTTPS
- The app runs on localhost only — no external access by default
- Read-only scope (`gmail.readonly`) means the app literally cannot send, delete, or modify any emails

---

## Updated `.env.example`

```
# LLM
GEMINI_API_KEY=your-gemini-api-key

# Gmail Integration (optional)
GOOGLE_CREDENTIALS_PATH=credentials.json
```

---

## README Additions

Add a new section to README.md:

### Gmail Integration (Optional)

jenax can connect to your Gmail to scan emails and extract action items. This is entirely optional — the app works fine without it.

**Setup:**

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use an existing one)
3. Go to **APIs & Services → Library**, search for "Gmail API", and click **Enable**
4. Go to **APIs & Services → Credentials**
5. Click **Configure Consent Screen**:
   - Choose **External**
   - App name: "jenax"
   - Add your email as a test user
   - Add scope: `https://www.googleapis.com/auth/gmail.readonly`
   - Save (no need to publish — testing mode works for personal use)
6. Go back to **Credentials → Create Credentials → OAuth Client ID**:
   - Application type: **Web application**
   - Authorized redirect URIs: `http://localhost:5000/auth/gmail/callback`
   - Download the JSON file and save it as `credentials.json` in the jenax folder
7. Start jenax and click "Connect Gmail" in the sidebar

**Privacy:** Your emails are sent to Google's Gemini API for summarization. They are not stored on any external server. Only the last 24 hours of emails are scanned, and automated/marketing emails are filtered out. You can disconnect at any time.

---

## Implementation Order

Build in this exact sequence:

1. **Database tables** — add the three new tables in `database.py` initialization. Add source='email' support to daily_tasks.

2. **`gmail_client.py`** — implement OAuth flow (get_auth_url, handle_callback, get_gmail_service, is_connected, disconnect) and email fetching (fetch_recent_emails). Test OAuth flow manually in the browser.

3. **OAuth routes in `app.py`** — add the `/auth/gmail/*` routes. Test the full connect → callback → status flow.

4. **`email_processor.py`** — implement the Gemini prompt for email analysis. Test with sample email data before connecting to real Gmail.

5. **Email API routes in `app.py`** — add `/api/email/*` routes. Test scan → digest → accept/dismiss flow.

6. **Frontend: sidebar connection UI** — add the Gmail connection status and connect/disconnect buttons.

7. **Frontend: email digest section** — add the full digest UI with summary, categories, and action items.

8. **Frontend: privacy notice modal** — add the one-time notice.

9. **Integration with plan generation** — update the planning prompt to include pending email action items.

10. **Cleanup and error handling** — add the 7-day cleanup, handle all error cases, test edge cases.