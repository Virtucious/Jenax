# jenax Phase 5 — Multi-Agent System

## Context

jenax Phases 1-4 are complete and running. The app has:
- Goal hierarchy with CRUD (yearly → monthly → weekly)
- AI-generated daily tasks via Gemini Flash
- Task carry-forward, end-of-day reviews, weekly reviews
- Smarter plan generation using review history and patterns
- Gmail integration with OAuth, email scanning, action item extraction
- Telegram bot with full command set and inline keyboards
- APScheduler for automated morning plans, evening reminders, email scans
- Browser notifications
- Progress stats, streaks, trends
- Single-page Flask app, SQLite database, Tailwind CSS frontend

This phase refactors the existing single-prompt AI into a **multi-agent architecture** where specialized agents handle different domains. Each agent has its own persona, context window, and prompt template, but they all share the same database and use the same Gemini API.

Do NOT break any existing functionality. The app should work identically from the user's perspective — what changes is the quality and depth of AI outputs.

---

## Architecture Overview

### What Is an "Agent" in This System?

An agent is NOT a separate process, server, or model. It is:
- A **prompt template** with a specific persona and instruction set
- A **context builder** that gathers the right data from the database for that agent's domain
- A **response parser** that handles the agent's structured output
- An **entry in the database** tracking the agent's outputs over time

All agents call the same Gemini Flash API. The difference is what context they receive and what they're asked to do.

### The Agents

| Agent | Role | Triggers |
|-------|------|----------|
| **Planner** | Daily task generation, schedule optimization | Morning routine, manual "Generate Plan" button |
| **Email** | Email triage, action extraction, reply drafting suggestions | Email scan (scheduled or manual) |
| **Research** | Learning path tracking, resource finding, course/book progress | When goals involve learning, manual "Research" button |
| **Accountability** | Pattern analysis, behavioral nudges, goal health monitoring | Weekly review, streak breaks, goal neglect detection |
| **Orchestrator** | Coordinates agents, resolves conflicts, produces final output | Runs before final output is shown to user |

### How They Work Together

```
User clicks "Generate Plan"
        │
        ▼
   Orchestrator
        │
        ├── Calls Planner Agent
        │     → gets task list based on goals + history
        │
        ├── Calls Email Agent (if Gmail connected)
        │     → gets pending email action items
        │
        ├── Calls Research Agent (if learning goals exist)
        │     → gets learning tasks and resource suggestions
        │
        ├── Calls Accountability Agent
        │     → gets behavioral nudges and warnings
        │
        ▼
   Orchestrator merges all outputs
        │
        ▼
   Final plan shown to user
```

This is a **sequential pipeline**, not parallel. Each agent runs one after another. The orchestrator collects all outputs and does a final merge/dedup pass.

---

## Project Structure (New/Modified Files)

```
jenax/
├── ... (existing files)
├── agents/
│   ├── __init__.py
│   ├── base.py              # Base agent class
│   ├── orchestrator.py       # Orchestrator — coordinates all agents
│   ├── planner_agent.py      # Daily planning specialist
│   ├── email_agent.py        # Email triage specialist
│   ├── research_agent.py     # Learning & research specialist
│   └── accountability_agent.py  # Behavioral patterns specialist
├── planner.py                # MODIFIED — now delegates to agents/orchestrator.py
└── email_processor.py        # MODIFIED — now delegates to agents/email_agent.py
```

---

## Database Changes

### Table: `agent_logs`
```sql
CREATE TABLE IF NOT EXISTS agent_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    trigger_type TEXT NOT NULL,         -- 'scheduled', 'manual', 'orchestrated'
    input_summary TEXT,                 -- brief description of what context was sent
    raw_prompt TEXT,                    -- the full prompt sent to Gemini (for debugging)
    raw_response TEXT,                  -- the raw response from Gemini
    parsed_output TEXT,                 -- the parsed JSON output
    tokens_used INTEGER,               -- approximate token count
    duration_ms INTEGER,               -- how long the call took
    success BOOLEAN DEFAULT 1,
    error_message TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `learning_resources`
```sql
CREATE TABLE IF NOT EXISTS learning_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id) ON DELETE CASCADE,
    type TEXT CHECK(type IN ('book', 'course', 'tutorial', 'article', 'video', 'other')),
    title TEXT NOT NULL,
    author TEXT,
    url TEXT,
    total_units INTEGER,               -- total chapters, modules, lessons, pages, etc.
    completed_units INTEGER DEFAULT 0,
    unit_label TEXT DEFAULT 'chapter',  -- 'chapter', 'module', 'lesson', 'page', etc.
    status TEXT DEFAULT 'in_progress' CHECK(status IN ('not_started', 'in_progress', 'completed', 'dropped')),
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `accountability_insights`
```sql
CREATE TABLE IF NOT EXISTS accountability_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_type TEXT NOT NULL,         -- 'pattern', 'warning', 'nudge', 'celebration'
    title TEXT NOT NULL,
    description TEXT,
    related_goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
    severity TEXT CHECK(severity IN ('info', 'warning', 'critical')),
    acknowledged BOOLEAN DEFAULT 0,     -- user has seen/dismissed this
    valid_until DATE,                   -- insight expires after this date
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Backend: `agents/base.py`

### Base Agent Class

All agents inherit from this. It handles the Gemini API call, logging, error handling, and response parsing.

```python
import time
import json
import google.generativeai as genai
from database import get_db

class BaseAgent:
    """Base class for all jenax agents."""
    
    def __init__(self, name, persona):
        """
        name: agent identifier (e.g., 'planner', 'email', 'research', 'accountability')
        persona: opening line of the system prompt describing who this agent is
        """
        self.name = name
        self.persona = persona
        self.model = genai.GenerativeModel("gemini-2.0-flash")
    
    def build_context(self):
        """
        Override in subclass. 
        Gathers relevant data from the database for this agent's domain.
        Returns: dict of context data
        """
        raise NotImplementedError
    
    def build_prompt(self, context, extra_input=None):
        """
        Override in subclass.
        Constructs the full prompt from persona + context + instructions.
        Returns: string prompt
        """
        raise NotImplementedError
    
    def parse_response(self, raw_text):
        """
        Override in subclass.
        Parses the raw LLM response into structured data.
        Returns: parsed dict
        """
        # Default: try JSON parsing
        cleaned = raw_text.strip()
        if cleaned.startswith('```'):
            cleaned = cleaned.split('\n', 1)[1]
            if cleaned.endswith('```'):
                cleaned = cleaned[:-3]
        return json.loads(cleaned)
    
    def run(self, extra_input=None, trigger_type='manual'):
        """
        Execute the agent:
        1. Build context from database
        2. Build prompt
        3. Call Gemini
        4. Parse response
        5. Log everything
        Returns: parsed output dict
        """
        start_time = time.time()
        context = self.build_context()
        prompt = self.build_prompt(context, extra_input)
        
        try:
            response = self.model.generate_content(prompt)
            raw_text = response.text
            parsed = self.parse_response(raw_text)
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Log to database
            self._log(
                trigger_type=trigger_type,
                input_summary=self._summarize_context(context),
                raw_prompt=prompt,
                raw_response=raw_text,
                parsed_output=json.dumps(parsed),
                duration_ms=duration_ms,
                success=True
            )
            
            return parsed
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self._log(
                trigger_type=trigger_type,
                input_summary=self._summarize_context(context),
                raw_prompt=prompt,
                raw_response=str(e),
                parsed_output=None,
                duration_ms=duration_ms,
                success=False,
                error_message=str(e)
            )
            raise
    
    def _log(self, **kwargs):
        """Save agent run to agent_logs table."""
        db = get_db()
        db.execute(
            """INSERT INTO agent_logs 
               (agent_name, trigger_type, input_summary, raw_prompt, 
                raw_response, parsed_output, duration_ms, success, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (self.name, kwargs['trigger_type'], kwargs['input_summary'],
             kwargs['raw_prompt'], kwargs['raw_response'], kwargs['parsed_output'],
             kwargs['duration_ms'], kwargs['success'], kwargs.get('error_message'))
        )
        db.commit()
    
    def _summarize_context(self, context):
        """Brief description of context for logging."""
        return f"{len(str(context))} chars of context"
```

---

## Backend: `agents/planner_agent.py`

This replaces the planning logic currently in `planner.py`.

### Persona
```
You are the Planner — a focused productivity strategist. Your job is to 
create realistic, prioritized daily task lists. You think in terms of 
energy management, task sequencing, and momentum. You front-load important 
work and protect the user from overcommitting.
```

### Context Builder
Gathers:
- All active goals (full hierarchy)
- Last 7 days of task history (completed/incomplete)
- Yesterday's daily reflection + tomorrow suggestions
- Latest weekly review focus areas
- Carried-forward tasks
- Day-of-week completion patterns
- Current streaks and trends
- Any inputs from other agents (passed via extra_input from orchestrator)

### Prompt Structure
```
{persona}

## User's Active Goals
{goal hierarchy}

## Recent Task History (Last 7 Days)
{daily breakdown}

## Yesterday's Reflection
{reflection + tomorrow_suggestions}

## Weekly Focus Areas
{from latest weekly review}

## Carried Forward Tasks
{incomplete tasks from yesterday}

## Inputs from Other Agents
{email action items from Email Agent, if any}
{learning tasks from Research Agent, if any}
{warnings from Accountability Agent, if any}

## Day-of-Week Patterns
{completion rates by day of week, today is {day}}

## Rules
1. Generate 5-8 tasks maximum.
2. Each task must be concrete and completable in one sitting (30min - 2hrs).
3. Sequence tasks by energy: hardest/most important in positions 1-3.
4. Include 1 quick win (under 15 minutes).
5. If other agents flagged items, integrate them — don't just append.
6. If a task has been carried forward 3+ times, either break it smaller or recommend dropping it.
7. Total estimated time should not exceed 6 hours of focused work.
8. If it's a historically low-completion day, generate fewer tasks (4-5 instead of 7-8).

Respond ONLY with valid JSON:
{
  "tasks": [
    {
      "title": "...",
      "description": "...",
      "priority": "high|medium|low",
      "goal_id": <id or null>,
      "estimated_minutes": <number>,
      "energy_level": "high|medium|low",
      "sequence_reason": "Why this task is in this position"
    }
  ],
  "daily_insight": "One sentence of strategic advice",
  "workload_assessment": "light|moderate|heavy",
  "flags": ["any warnings or notes for the orchestrator"]
}
```

---

## Backend: `agents/email_agent.py`

This replaces the processing logic currently in `email_processor.py`.

### Persona
```
You are the Email Analyst — an executive assistant who triages inboxes 
with precision. You distinguish between truly urgent items and things 
that just feel urgent. You protect the user's focus by being ruthlessly 
selective about what deserves their attention.
```

### Context Builder
Gathers:
- Recent emails (from gmail_client.fetch_recent_emails)
- User's active goals (so the agent can prioritize emails related to goals)
- Today's existing tasks (to avoid duplicating action items)
- Previous email digests (last 3 days, to track email threads)

### Prompt Structure
```
{persona}

## Recent Emails (Last 24 Hours)
{email list with sender, subject, body}

## User's Current Priorities
{active goals, today's tasks}

## Previous Digests (Context)
{summaries from last 3 days — helps track ongoing threads}

## Instructions
1. Categorize each email: needs_reply, action_required, informational, can_ignore
2. Extract action items ONLY for things that genuinely require the user's effort
3. For "needs_reply" emails, draft a 1-2 sentence reply suggestion
4. Prioritize emails that relate to the user's active goals
5. Flag any email threads that have been going back and forth without resolution
6. If an email is from an unknown sender about something important, note it

Respond ONLY with valid JSON:
{
  "summary": "2-4 sentence inbox overview",
  "action_items": [
    {
      "title": "...",
      "description": "...",
      "priority": "high|medium|low",
      "source_subject": "...",
      "source_sender": "...",
      "suggested_reply": "Draft reply if this is a needs_reply item, or null",
      "related_goal_id": <goal id if related to a goal, or null>,
      "urgency_reason": "Why this priority level"
    }
  ],
  "categories": {
    "needs_reply": <number>,
    "action_required": <number>,
    "informational": <number>,
    "can_ignore": <number>
  },
  "thread_alerts": [
    {
      "subject": "...",
      "message": "This thread has had 5 back-and-forth emails — consider scheduling a call"
    }
  ],
  "flags": ["any notes for the orchestrator"]
}
```

---

## Backend: `agents/research_agent.py`

This is entirely new — no existing code to refactor.

### Persona
```
You are the Research Coach — a learning strategist who helps people 
make consistent progress on educational goals. You break down learning 
into daily bite-sized tasks, track progress through courses and books, 
and suggest resources. You believe in spaced repetition, active recall, 
and the power of showing up every day even for just 20 minutes.
```

### Context Builder
Gathers:
- Active goals that involve learning (detect by keywords in title/description: "learn", "course", "book", "read", "study", "tutorial", "certification", "skill")
- Learning resources linked to those goals (from `learning_resources` table)
- Recent learning-related task completions
- Progress data on each resource (completed_units / total_units)

### Prompt Structure
```
{persona}

## Learning Goals
{learning-related goals with their sub-goals}

## Active Learning Resources
{for each resource:
  "Title: [title] by [author]
   Type: [book/course/etc]
   Progress: [completed_units]/[total_units] [unit_label]s
   Status: [in_progress/not_started]
   Notes: [any user notes]"
}

## Recent Learning Activity (Last 7 Days)
{learning-related tasks completed recently}

## Today's Date: {date}
## Days Until Goal Deadlines: {for each learning goal with a deadline}

## Instructions
1. For each active learning resource, suggest a specific task for today
2. Tasks should be small and completable in 20-45 minutes
3. Use spaced repetition logic: if the user studied something 2 days ago, suggest reviewing it
4. If a resource is falling behind schedule (based on deadline), flag it and suggest catching up
5. If no learning resources are tracked yet but learning goals exist, suggest resources the user could start with
6. If the user has too many resources in progress, suggest focusing on 1-2 at a time

Respond ONLY with valid JSON:
{
  "learning_tasks": [
    {
      "title": "...",
      "description": "...",
      "priority": "high|medium|low",
      "goal_id": <related goal id>,
      "resource_id": <related resource id or null>,
      "estimated_minutes": <number>,
      "task_type": "new_content|review|practice|project"
    }
  ],
  "resource_suggestions": [
    {
      "title": "Suggested resource title",
      "type": "book|course|tutorial|article|video",
      "reason": "Why this would help with their goal",
      "goal_id": <related goal id>
    }
  ],
  "progress_alerts": [
    {
      "resource_id": <id>,
      "message": "You're 3 chapters behind schedule for [resource]. Consider doing 2 chapters today."
    }
  ],
  "flags": ["any notes for the orchestrator"]
}
```

### Learning Resource Management

The Research Agent also needs CRUD support for learning resources.

**New API routes:**

- `GET /api/resources` — list all learning resources, optionally filtered by goal_id
- `POST /api/resources` — create a resource: `{goal_id, type, title, author, url, total_units, unit_label}`
- `PUT /api/resources/<id>` — update a resource
- `PATCH /api/resources/<id>/progress` — update progress: `{completed_units}`
- `DELETE /api/resources/<id>` — delete a resource

---

## Backend: `agents/accountability_agent.py`

This is entirely new.

### Persona
```
You are the Accountability Partner — a supportive but honest coach who 
tracks behavioral patterns over time. You notice when someone is 
avoiding certain goals, when their productivity is declining, and when 
they deserve celebration. You don't lecture — you observe, ask good 
questions, and nudge gently. But you don't let important things slide.
```

### Context Builder
Gathers:
- Full goal list with statuses and creation dates
- 30-day task completion history (daily: completed/total)
- All daily reflections from the last 30 days
- All weekly reviews from the last month
- Streak data (current, longest, recent breaks)
- Goal activity map: for each goal, when was the last task completed?
- Previous accountability insights (to avoid repeating the same observation)
- Day-of-week and time-of-day patterns

### Prompt Structure
```
{persona}

## Goal Health Report
{for each goal:
  "Goal: [title] (level: [level], created: [date], deadline: [deadline])
   Status: [active/paused/etc]
   Last task completed: [date] ([X days ago])
   Tasks completed (30 days): [count]
   Tasks missed (30 days): [count]
   Sub-goals: [count active / count total]"
}

## 30-Day Completion Trend
{daily completion rates for last 30 days, formatted as a simple list}

## Behavioral Patterns
Day-of-week averages: {Mon: 75%, Tue: 80%, ..., Sun: 40%}
Best streak: {longest_streak} days
Current streak: {current_streak} days
Recent streak breaks: {dates when streaks broke}

## Previous Insights (avoid repeating these)
{last 5 accountability insights with dates}

## Recent Mood Trend
{moods from daily reflections, last 14 days}

## Instructions
1. Identify 2-4 insights about the user's productivity patterns
2. Each insight should be one of:
   - "pattern": a recurring behavior (good or bad)
   - "warning": a goal or habit that's at risk
   - "nudge": a gentle push toward something being avoided
   - "celebration": recognition of progress or consistency
3. Be specific — reference actual goals, dates, and numbers
4. Don't repeat insights from the "Previous Insights" section
5. If mood has been declining, note it sensitively
6. Set a valid_until date: patterns last 14 days, warnings last 7 days, celebrations last 3 days
7. Assign severity: info (observations), warning (needs attention), critical (goal at serious risk)

Respond ONLY with valid JSON:
{
  "insights": [
    {
      "type": "pattern|warning|nudge|celebration",
      "title": "Short title",
      "description": "2-3 sentence observation with specific data references",
      "related_goal_id": <goal id or null>,
      "severity": "info|warning|critical",
      "valid_days": <number of days this insight stays relevant>,
      "suggested_action": "What the user could do about it, or null for celebrations"
    }
  ],
  "overall_health": "thriving|steady|struggling|critical",
  "flags": ["any urgent notes for the orchestrator"]
}
```

---

## Backend: `agents/orchestrator.py`

The orchestrator coordinates all agents and merges their outputs.

### How It Works

```python
class Orchestrator:
    """
    Coordinates all agents and produces a unified output.
    This is NOT an LLM agent — it's procedural Python code.
    """
    
    def __init__(self):
        self.planner = PlannerAgent()
        self.email_agent = EmailAgent()
        self.research_agent = ResearchAgent()
        self.accountability_agent = AccountabilityAgent()
    
    def generate_daily_plan(self):
        """
        Full daily plan generation pipeline.
        Runs agents in sequence, passes outputs between them.
        Returns: merged plan with tasks, insights, and alerts.
        """
        
        results = {}
        
        # Step 1: Accountability check (runs first to provide warnings)
        try:
            results['accountability'] = self.accountability_agent.run(
                trigger_type='orchestrated'
            )
            self._save_insights(results['accountability'])
        except Exception as e:
            results['accountability'] = None
            # Log but don't fail — other agents can still run
        
        # Step 2: Email triage (if Gmail connected)
        if is_gmail_connected():
            try:
                emails = fetch_recent_emails(hours=24)
                results['email'] = self.email_agent.run(
                    extra_input={'emails': emails},
                    trigger_type='orchestrated'
                )
            except Exception as e:
                results['email'] = None
        
        # Step 3: Research tasks (if learning goals exist)
        if has_learning_goals():
            try:
                results['research'] = self.research_agent.run(
                    trigger_type='orchestrated'
                )
            except Exception as e:
                results['research'] = None
        
        # Step 4: Planner (receives outputs from all other agents)
        agent_inputs = {
            'email_actions': self._extract_email_actions(results.get('email')),
            'learning_tasks': self._extract_learning_tasks(results.get('research')),
            'accountability_warnings': self._extract_warnings(results.get('accountability')),
        }
        
        try:
            results['planner'] = self.planner.run(
                extra_input=agent_inputs,
                trigger_type='orchestrated'
            )
        except Exception as e:
            # If planner fails, this is critical — re-raise
            raise
        
        # Step 5: Merge and deduplicate
        final_output = self._merge_outputs(results)
        
        return final_output
    
    def _merge_outputs(self, results):
        """
        Combine all agent outputs into a single response.
        
        Merging rules:
        1. Tasks come primarily from the Planner
        2. Email action items are shown separately (not mixed into the task list)
        3. Research suggestions are shown as a separate section
        4. Accountability insights are shown as alerts/banners
        5. Deduplicate: if planner already included an email task or learning task, 
           don't show it again in the separate sections
        """
        
        planner_output = results.get('planner', {})
        email_output = results.get('email')
        research_output = results.get('research')
        accountability_output = results.get('accountability')
        
        return {
            'tasks': planner_output.get('tasks', []),
            'daily_insight': planner_output.get('daily_insight', ''),
            'workload_assessment': planner_output.get('workload_assessment', 'moderate'),
            
            'email_summary': email_output.get('summary') if email_output else None,
            'email_action_items': email_output.get('action_items', []) if email_output else [],
            'thread_alerts': email_output.get('thread_alerts', []) if email_output else [],
            
            'learning_tasks': research_output.get('learning_tasks', []) if research_output else [],
            'resource_suggestions': research_output.get('resource_suggestions', []) if research_output else [],
            'progress_alerts': research_output.get('progress_alerts', []) if research_output else [],
            
            'accountability_insights': accountability_output.get('insights', []) if accountability_output else [],
            'overall_health': accountability_output.get('overall_health', 'steady') if accountability_output else 'steady',
            
            'agents_used': [k for k, v in results.items() if v is not None]
        }
    
    def _save_insights(self, accountability_output):
        """Save accountability insights to the database."""
        if not accountability_output:
            return
        for insight in accountability_output.get('insights', []):
            # Calculate valid_until date
            valid_days = insight.get('valid_days', 7)
            # Insert into accountability_insights table
            # Skip if a similar insight (same title) already exists and is still valid
    
    def _extract_email_actions(self, email_output):
        """Extract action items for the planner's context."""
        if not email_output:
            return []
        return [
            f"[{item['priority']}] {item['title']} (from: {item['source_sender']})"
            for item in email_output.get('action_items', [])
        ]
    
    def _extract_learning_tasks(self, research_output):
        """Extract learning tasks for the planner's context."""
        if not research_output:
            return []
        return [
            f"{task['title']} (~{task['estimated_minutes']}min, {task['task_type']})"
            for task in research_output.get('learning_tasks', [])
        ]
    
    def _extract_warnings(self, accountability_output):
        """Extract warnings for the planner's context."""
        if not accountability_output:
            return []
        return [
            f"[{insight['severity']}] {insight['title']}: {insight['description']}"
            for insight in accountability_output.get('insights', [])
            if insight['severity'] in ('warning', 'critical')
        ]
```

### Integration with Existing Code

**Modify `planner.py`:**
The existing `generate_plan()` function should now delegate to the orchestrator:

```python
from agents.orchestrator import Orchestrator

def generate_plan():
    """
    Entry point for plan generation.
    Now uses the multi-agent orchestrator instead of a single prompt.
    Falls back to single-prompt mode if agents fail.
    """
    orchestrator = Orchestrator()
    try:
        return orchestrator.generate_daily_plan()
    except Exception as e:
        # Fallback: use the old single-prompt approach
        return generate_plan_legacy()
```

Keep the old single-prompt logic as `generate_plan_legacy()` for fallback.

**Modify `email_processor.py`:**
Similarly delegate to the email agent, with the old logic as fallback.

---

## API Route Changes

### Modified Routes

**`POST /api/generate-plan`**
- Now returns the enriched orchestrator output:
```json
{
  "tasks": [...],
  "daily_insight": "...",
  "workload_assessment": "moderate",
  "email_summary": "...",
  "email_action_items": [...],
  "learning_tasks": [...],
  "resource_suggestions": [...],
  "accountability_insights": [...],
  "overall_health": "steady",
  "agents_used": ["planner", "email", "research", "accountability"]
}
```

### New Routes

**`GET /api/resources`** — list learning resources
**`POST /api/resources`** — create a learning resource
**`PUT /api/resources/<id>`** — update a learning resource
**`PATCH /api/resources/<id>/progress`** — update progress `{completed_units}`
**`DELETE /api/resources/<id>`** — delete a learning resource

**`GET /api/insights`** — get active accountability insights (not expired, not acknowledged)
**`PATCH /api/insights/<id>/acknowledge`** — mark an insight as acknowledged

**`GET /api/agents/logs?agent=planner&limit=10`** — get recent agent logs (for debugging)
**`GET /api/agents/status`** — returns which agents are available and their last run time:
```json
{
  "agents": [
    {"name": "planner", "available": true, "last_run": "2025-04-01T07:00:00", "last_status": "success"},
    {"name": "email", "available": true, "last_run": "2025-04-01T08:00:00", "last_status": "success"},
    {"name": "research", "available": true, "last_run": "2025-04-01T07:00:00", "last_status": "success"},
    {"name": "accountability", "available": true, "last_run": "2025-03-31T07:00:00", "last_status": "success"}
  ]
}
```

---

## Frontend Changes

### Dashboard Restructure

The main dashboard content area now has richer sections reflecting multi-agent output. The layout order from top to bottom:

**1. Accountability Alerts (if any critical/warning insights exist)**
```
┌─────────────────────────────────────────────────┐
│ ⚠️ Your "Read 12 books" goal has had zero       │
│ activity for 12 days. Consider picking up your   │
│ current book today, even for just 20 minutes.    │
│                               [Got it] [Snooze]  │
└─────────────────────────────────────────────────┘
```
- Critical insights: red left border
- Warning insights: amber left border
- Info insights: blue left border (shown in a collapsible section, not as banners)
- Celebrations: green left border with confetti-style accent
- "Got it" marks as acknowledged. "Snooze" hides for 24 hours (set acknowledged but with a reset timer — or simply re-show next day if still valid).

**2. Daily Insight + Workload Badge**
```
┌─────────────────────────────────────────────────┐
│ 💡 "Focus on Python today — you've been          │
│ avoiding it since Tuesday."                      │
│                                                  │
│ Workload: 🟡 Moderate (~4.5 hrs focused work)    │
│ Health: 🟢 Steady                                │
│                                    [Generate Plan]│
└─────────────────────────────────────────────────┘
```
- Workload badge: 🟢 Light / 🟡 Moderate / 🔴 Heavy
- Health badge from accountability agent: 🟢 Thriving / 🟡 Steady / 🟠 Struggling / 🔴 Critical

**3. Today's Tasks (same as before but with energy labels)**
- Each task now optionally shows an energy tag: `⚡ High energy` / `☕ Medium` / `🌿 Low energy`
- Tasks are still checkable, same interaction as before

**4. Learning Corner (only if Research Agent returned data)**
```
┌─────────────────────────────────────────────────┐
│ 📚 Learning Corner                               │
│                                                  │
│ Python Crash Course ████████░░ 8/12 chapters     │
│   Today: Complete Chapter 9 exercises (~30min)   │
│   ⚠️ 2 chapters behind schedule                  │
│                                                  │
│ Atomic Habits ██████░░░░ 120/280 pages           │
│   Today: Read pages 121-150 (~30min)             │
│                                                  │
│ 💡 Suggested: "Automate the Boring Stuff"        │
│    Great complement to your Python course goal   │
│                            [Add to Resources]    │
│                                                  │
│              [Manage Resources]                  │
└─────────────────────────────────────────────────┘
```
- Progress bars for each active resource
- Today's learning task inline
- Resource suggestions with one-click add
- "Manage Resources" opens a modal for CRUD on learning_resources

**5. Email Digest (same as Phase 3 but with reply suggestions)**
- Same layout as before
- Action items now show "Suggested reply" expandable section if the email agent provided one
- Thread alerts shown as a small callout below the digest

**6. Progress & Stats (same as before)**

### Sidebar Addition: Agent Status

At the bottom of the sidebar, below Connections and Automation:

```
── Agents ──────────────────
🧠 Planner        ✓ 7:00 AM
📧 Email          ✓ 8:00 AM
📚 Research       ✓ 7:00 AM
👁 Accountability ✓ 7:00 AM

[View Logs]
```

- Each agent shows its last run time and status (✓ success, ✗ failed, ⏳ running)
- "View Logs" opens a modal showing recent agent_logs entries (filterable by agent)
- This is mostly a debugging/transparency feature — helps the user understand what's happening under the hood

### Learning Resources Modal

Accessed via "Manage Resources" button in Learning Corner:

```
┌─────────────────────────────────────────────────┐
│ 📚 Learning Resources                    [+ Add]│
│                                                  │
│ ┌─────────────────────────────────────────────┐  │
│ │ Python Crash Course          📖 Book        │  │
│ │ by Eric Matthes                             │  │
│ │ Goal: Complete Python course                │  │
│ │ Progress: 8/12 chapters                     │  │
│ │ [Update Progress] [Edit] [Delete]           │  │
│ ├─────────────────────────────────────────────┤  │
│ │ CS50 Web Programming         🎓 Course      │  │
│ │ by Harvard (edX)                            │  │
│ │ Goal: Learn web development                 │  │
│ │ Progress: 3/11 modules                      │  │
│ │ [Update Progress] [Edit] [Delete]           │  │
│ └─────────────────────────────────────────────┘  │
│                                                  │
│ [+ Add] opens a form:                            │
│   Title: [________________]                      │
│   Author: [________________]                     │
│   Type: [book ▼]                                 │
│   URL: [________________] (optional)             │
│   Total units: [___]                             │
│   Unit label: [chapter ▼] (chapter/module/       │
│               lesson/page/section/video)         │
│   Linked goal: [dropdown of active goals]        │
│                          [Save] [Cancel]          │
└─────────────────────────────────────────────────┘
```

- "Update Progress" opens a small inline form: current units completed (number input) + Save
- Type icons: 📖 Book, 🎓 Course, 📝 Tutorial, 📄 Article, 🎥 Video, 📦 Other

---

## Telegram Bot Updates

### New Commands

**`/resources`**
- Lists active learning resources with progress:
  ```
  📚 Your Learning Resources
  
  1. Python Crash Course (Book)
     ████████░░ 8/12 chapters
  
  2. CS50 Web Programming (Course)
     ███░░░░░░░ 3/11 modules
  
  Use /progress_update <number> <units> to update
  (e.g., /progress_update 1 9)
  ```

**`/progress_update <resource_number> <completed_units>`**
- Updates the completed_units for a learning resource
- Replies: "📖 Updated 'Python Crash Course': 9/12 chapters (75%)"

**`/insights`**
- Shows active accountability insights:
  ```
  👁 Accountability Insights
  
  ⚠️ "Read 12 books" goal neglected
  No activity in 12 days. Even 20 minutes today helps.
  
  🎉 5-day streak!
  You've been consistent all week. Keep it going.
  
  📊 Overall health: Steady
  ```

### Modified Morning Plan Message

The morning Telegram message now includes sections from all agents:

```
📅 Your Plan for Monday, Mar 31

💡 "Focus on Python today — you've been avoiding it since Tuesday."
📊 Workload: Moderate (~4.5 hrs) | Health: Steady

📋 Tasks:
1. 🔴 ⚡ Complete Python Chapter 9 exercises (~45min)
2. 🔴 ⚡ Reply to Sarah about Q3 budget (~15min)
3. 🟡 ☕ Read 30 pages of Atomic Habits (~40min)
4. 🟡 ☕ Update resume skills section (~30min)
5. 🟢 🌿 Review and organize bookmarks (~15min)

📚 Learning:
• Python course: 8/12 chapters — ⚠️ 2 behind schedule
• Atomic Habits: 120/280 pages — on track

⚠️ Alert:
• "Read 12 books" goal — no activity in 12 days

[✓ 1] [✓ 2] [✓ 3] [✓ 4] [✓ 5]
```

---

## Performance Considerations

Running 4 agents sequentially means 4 Gemini API calls per plan generation. On Gemini Flash free tier:

- Each call takes ~2-4 seconds
- Total: ~8-16 seconds for a full plan
- Free tier: 15 requests/minute → 4 calls is fine, even with headroom

### Optimization Strategies

1. **Skip agents when unnecessary:**
   - Skip Email Agent if Gmail is not connected
   - Skip Research Agent if no goals have learning-related keywords
   - Skip Accountability Agent if it ran within the last 6 hours (cache the output)

2. **Cache accountability insights:**
   - The Accountability Agent's output changes slowly (daily patterns, not hourly)
   - Run it once per day (during morning routine) and cache the result
   - The orchestrator uses cached output instead of re-running

3. **Show progressive results in the UI:**
   - Don't wait for all agents to finish before showing anything
   - As each agent completes, update the relevant section of the dashboard
   - Implementation: use Server-Sent Events (SSE) or poll a status endpoint

**Recommended approach for progressive loading:**

Create a `POST /api/generate-plan/stream` endpoint that returns agent results as they complete:

```python
from flask import Response, stream_with_context
import json

@app.route('/api/generate-plan/stream', methods=['POST'])
def generate_plan_stream():
    def generate():
        orchestrator = Orchestrator()
        
        # Step 1: Accountability
        yield json.dumps({"agent": "accountability", "status": "running"}) + "\n"
        result = orchestrator.run_accountability()
        yield json.dumps({"agent": "accountability", "status": "done", "data": result}) + "\n"
        
        # Step 2: Email
        yield json.dumps({"agent": "email", "status": "running"}) + "\n"
        result = orchestrator.run_email()
        yield json.dumps({"agent": "email", "status": "done", "data": result}) + "\n"
        
        # ... etc for each agent
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/plain',
        headers={'X-Content-Type-Options': 'nosniff'}
    )
```

Frontend reads the stream and updates each section as data arrives:
```javascript
const response = await fetch('/api/generate-plan/stream', { method: 'POST' });
const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    
    const lines = decoder.decode(value).split('\n').filter(Boolean);
    for (const line of lines) {
        const update = JSON.parse(line);
        updateAgentSection(update.agent, update.status, update.data);
    }
}
```

This way the user sees each section populate in real-time instead of staring at a spinner for 15 seconds.

---

## Error Handling

- If any single agent fails, the orchestrator continues with the remaining agents. Only a Planner failure is critical (raises an error and falls back to legacy single-prompt mode).
- All agent errors are logged to `agent_logs` with `success=False` and the error message.
- The frontend shows which agents succeeded/failed in the agent status sidebar.
- If the Gemini API rate limit is hit mid-pipeline, wait 10 seconds and retry once. If it fails again, skip that agent.
- Agent logs older than 30 days should be cleaned up by the scheduler (add to the data_cleanup job).

---

## Implementation Order

Build in this exact sequence:

1. **`agents/base.py`** — Base agent class with Gemini call, logging, error handling. Create `agent_logs` table. Test with a dummy agent.

2. **`agents/planner_agent.py`** — Port existing planning logic to the agent pattern. Verify it produces identical output to the current system. Keep old code as fallback.

3. **`agents/orchestrator.py`** — Basic orchestrator that only runs the planner agent. Wire it into `POST /api/generate-plan`. Verify the existing flow still works.

4. **`agents/email_agent.py`** — Port existing email processing to agent pattern. Wire into orchestrator. Verify email scanning still works.

5. **`agents/accountability_agent.py`** — New agent. Create `accountability_insights` table. Test standalone via a temporary API endpoint.

6. **`agents/research_agent.py`** — New agent. Create `learning_resources` table. Build CRUD routes for resources. Test standalone.

7. **Orchestrator full pipeline** — Wire all 4 agents into the orchestrator. Test the complete flow. Implement skip logic for unavailable agents.

8. **Frontend: accountability alerts** — Add insight banners at top of dashboard.

9. **Frontend: learning corner** — Add the learning section with progress bars, resource management modal.

10. **Frontend: agent status sidebar** — Add the agent status display.

11. **Frontend: progressive loading** — Implement SSE/streaming for plan generation so sections populate as agents complete.

12. **Telegram updates** — Add `/resources`, `/progress_update`, `/insights` commands. Update morning plan message format.

13. **Performance optimization** — Add accountability caching, agent skip logic, log cleanup.

## Important Notes

- The multi-agent system should be a TRANSPARENT upgrade. If the user doesn't add any learning resources, the Research Agent simply doesn't run. If Gmail isn't connected, the Email Agent is skipped. The minimum viable experience is the same as Phase 1: just the Planner generating tasks.
- Keep the legacy single-prompt plan generation as a fallback. If the orchestrator fails entirely, fall back silently.
- Each agent's prompt is independent — they don't see each other's full prompts. The orchestrator passes only extracted summaries between them (not raw outputs).
- Be careful with prompt size. Each agent's context should stay under ~4000 tokens of input. The Planner agent receives the most context (its own data + summaries from other agents) but should still stay well within Gemini Flash's context window.
- Agent logs can grow fast (4 entries per plan generation). The 30-day cleanup in the scheduler job is important.
- The streaming endpoint is a nice-to-have. If it's too complex, a simpler approach is: generate the full plan (show a spinner for 10-15 seconds), then display everything at once. Implement streaming only if the wait feels too long in practice.