# Planwise Phase 6 — Smart Goal Decomposition Engine

## Context

Planwise Phases 1-5 are complete. This phase fundamentally upgrades how goals are created and how daily tasks are generated from them. Instead of vague goals producing vague tasks, the system now:

1. **Researches** goals using web search to understand their structure (chapters, modules, steps)
2. **Proposes** a structured breakdown that the user confirms or edits
3. **Schedules** work units across days based on deadlines, difficulty, and the user's actual pace
4. **Generates hyper-specific daily tasks** like "Read pages 141-165, do exercises 7.1-7.3" instead of "Work on Python book"
5. **Tracks pace** and adapts future scheduling based on real performance data
6. **Handles three goal types differently**: learning paths, career pipelines, and progressive/constant habits

Do NOT break any existing functionality. Existing goals without blueprints continue to work with the current generation logic. New features only activate when a goal has a blueprint attached.

---

## Core Concept: Goal Blueprints

A **blueprint** is the structured breakdown of a goal. It's the bridge between a vague goal ("Read Atomic Habits") and specific daily tasks ("Read pages 141-165").

Every goal can optionally have a blueprint. A blueprint contains:
- **Milestones**: major checkpoints (e.g., "Finish Part 2 of the book")
- **Work units**: the atomic pieces of work (e.g., "Chapter 7", "Exercise set 3.1-3.5", "Apply to 3 jobs")
- **Dependencies**: which units must come before others
- **Estimates**: how long each unit takes (AI-estimated, then refined by actual pace)
- **Schedule**: when each unit is planned to be completed

Blueprints are created during a **Goal Setup Wizard** — an interactive flow where the AI researches the goal, proposes a breakdown, and the user confirms or edits it.

---

## Database Changes

### Table: `goal_blueprints`
```sql
CREATE TABLE IF NOT EXISTS goal_blueprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER UNIQUE REFERENCES goals(id) ON DELETE CASCADE,
    blueprint_type TEXT NOT NULL CHECK(blueprint_type IN ('learning', 'career', 'habit')),
    title TEXT NOT NULL,
    source_info TEXT,                  -- JSON: what the AI found via web search (book metadata, course structure, etc.)
    total_units INTEGER,
    completed_units INTEGER DEFAULT 0,
    unit_label TEXT DEFAULT 'unit',    -- 'chapter', 'module', 'page', 'application', 'session', etc.
    schedule_strategy TEXT DEFAULT 'even' CHECK(schedule_strategy IN ('even', 'front_loaded', 'back_loaded', 'adaptive')),
    difficulty_curve TEXT,             -- JSON array: relative difficulty per unit (e.g., [1,1,1,2,2,3,2,1])
    estimated_pace_minutes REAL,       -- AI's initial estimate of minutes per unit
    actual_pace_minutes REAL,          -- updated as user completes units — rolling average
    pace_samples INTEGER DEFAULT 0,    -- how many completed units contributed to actual_pace
    status TEXT DEFAULT 'active' CHECK(status IN ('draft', 'active', 'completed', 'paused')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `blueprint_milestones`
```sql
CREATE TABLE IF NOT EXISTS blueprint_milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blueprint_id INTEGER REFERENCES goal_blueprints(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    target_date DATE,
    completed BOOLEAN DEFAULT 0,
    completed_at DATETIME,
    sort_order INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `blueprint_units`
```sql
CREATE TABLE IF NOT EXISTS blueprint_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blueprint_id INTEGER REFERENCES goal_blueprints(id) ON DELETE CASCADE,
    milestone_id INTEGER REFERENCES blueprint_milestones(id) ON DELETE SET NULL,
    title TEXT NOT NULL,                        -- "Chapter 7: Classes"
    description TEXT,                           -- "Covers class definitions, inheritance, and polymorphism"
    unit_number INTEGER NOT NULL,               -- sequential order
    estimated_minutes INTEGER,                  -- AI estimate for this specific unit
    actual_minutes INTEGER,                     -- logged after completion
    difficulty REAL DEFAULT 1.0,                -- relative difficulty multiplier (1.0 = average, 2.0 = twice as hard)
    scheduled_date DATE,                        -- when this unit is planned
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed', 'skipped')),
    completed_at DATETIME,
    depends_on INTEGER REFERENCES blueprint_units(id), -- prerequisite unit (null = no dependency)
    metadata TEXT,                              -- JSON: extra info (page range, exercise numbers, URLs, etc.)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `habit_config`
```sql
CREATE TABLE IF NOT EXISTS habit_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blueprint_id INTEGER UNIQUE REFERENCES goal_blueprints(id) ON DELETE CASCADE,
    frequency TEXT NOT NULL CHECK(frequency IN ('daily', 'weekdays', 'weekends', 'custom')),
    custom_days TEXT,                           -- JSON array: [1,2,3,4,5] for Mon-Fri (ISO weekday numbers)
    progression_type TEXT DEFAULT 'constant' CHECK(progression_type IN ('constant', 'progressive')),
    base_quantity REAL,                         -- starting amount (e.g., 2.0 for 2km, 20.0 for 20 pages)
    current_quantity REAL,                      -- current target
    target_quantity REAL,                       -- end goal (e.g., 5.0 for 5km) — null if constant
    quantity_unit TEXT,                         -- 'km', 'minutes', 'pages', 'reps', etc.
    increment_amount REAL,                     -- how much to increase per step
    increment_frequency TEXT DEFAULT 'weekly' CHECK(increment_frequency IN ('daily', 'weekly', 'biweekly', 'monthly')),
    last_increment_date DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `career_pipeline`
```sql
CREATE TABLE IF NOT EXISTS career_pipeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blueprint_id INTEGER REFERENCES goal_blueprints(id) ON DELETE CASCADE,
    entry_type TEXT NOT NULL CHECK(entry_type IN ('application', 'interview', 'portfolio_piece', 'networking', 'skill_gap')),
    title TEXT NOT NULL,                        -- "Applied to Google — SWE Intern" or "Portfolio: Weather App"
    company TEXT,                               -- for applications/interviews
    status TEXT,                                -- application: applied/screening/interview/offer/rejected
                                               -- portfolio: idea/in_progress/completed/published
                                               -- interview: scheduled/completed/passed/failed
    url TEXT,                                   -- job posting URL, portfolio link, etc.
    notes TEXT,
    deadline DATE,
    follow_up_date DATE,                        -- when to follow up
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Modify `daily_tasks` table
Add a column to link tasks to specific blueprint units:
```sql
ALTER TABLE daily_tasks ADD COLUMN blueprint_unit_id INTEGER REFERENCES blueprint_units(id) ON DELETE SET NULL;
```

When a task linked to a blueprint_unit is completed, automatically update the unit's status to 'completed' and log `actual_minutes`.

---

## Feature 1: Goal Setup Wizard

### User Flow

When the user creates a new goal (or edits an existing one), they see a "Create Smart Plan" button. Clicking it launches the wizard:

**Step 1: Goal Type Selection**
```
┌─────────────────────────────────────────────────┐
│ 🧠 Smart Goal Setup                             │
│                                                  │
│ What kind of goal is this?                       │
│                                                  │
│ ┌───────────┐ ┌───────────┐ ┌───────────┐       │
│ │ 📚        │ │ 💼        │ │ 🔄        │       │
│ │ Learning  │ │ Career    │ │ Habit     │       │
│ │           │ │           │ │           │       │
│ │ Books,    │ │ Job hunt, │ │ Exercise, │       │
│ │ courses,  │ │ portfolio,│ │ reading,  │       │
│ │ tutorials │ │ resume    │ │ practice  │       │
│ └───────────┘ └───────────┘ └───────────┘       │
└─────────────────────────────────────────────────┘
```

**Step 2: Goal Details (varies by type)**

For **Learning**:
```
┌─────────────────────────────────────────────────┐
│ 📚 Learning Goal Setup                           │
│                                                  │
│ What are you learning?                           │
│ [Read "Atomic Habits" by James Clear      ]      │
│                                                  │
│ Deadline (optional):                             │
│ [May 15, 2026    ]                               │
│                                                  │
│ Any notes? (e.g., "focus on Part 2")             │
│ [                                        ]       │
│                                                  │
│           [🔍 Research & Build Plan]             │
│                                                  │
│ ⏳ The AI will search for the book's structure   │
│    and propose a reading schedule.               │
└─────────────────────────────────────────────────┘
```

For **Career**:
```
┌─────────────────────────────────────────────────┐
│ 💼 Career Goal Setup                             │
│                                                  │
│ What's the career goal?                          │
│ [Get a junior web developer job            ]     │
│                                                  │
│ Target timeline:                                 │
│ [3 months ▼]                                     │
│                                                  │
│ What do you already have? (select all)           │
│ [✓] Resume                                       │
│ [ ] Portfolio with projects                      │
│ [ ] LinkedIn optimized                           │
│ [✓] Basic technical skills                       │
│ [ ] Interview practice                           │
│                                                  │
│           [🔍 Research & Build Plan]             │
└─────────────────────────────────────────────────┘
```

For **Habit**:
```
┌─────────────────────────────────────────────────┐
│ 🔄 Habit Setup                                   │
│                                                  │
│ What habit are you building?                     │
│ [Running / jogging                         ]     │
│                                                  │
│ How often?                                       │
│ (●) Daily  ( ) Weekdays  ( ) Weekends            │
│ ( ) Custom: [ ] M [✓] T [ ] W [✓] T [✓] F [ ] S [ ] S │
│                                                  │
│ Does this habit grow over time?                  │
│ (●) Progressive    ( ) Constant                  │
│                                                  │
│ Starting amount: [2   ] [km ▼]                   │
│ Target amount:   [5   ] [km ▼]                   │
│ Increase every:  [week ▼]  by: [0.5]            │
│                                                  │
│              [Create Habit Plan]                 │
└─────────────────────────────────────────────────┘
```

**Step 3: AI Research (for Learning and Career types)**

When user clicks "Research & Build Plan":

1. Show a loading state: "🔍 Researching..." with progress messages:
   - "Searching for book structure..."
   - "Finding chapter details..."
   - "Building your schedule..."

2. The system calls Gemini with web search enabled to find:
   - For books: table of contents, chapter count, page counts, difficulty notes
   - For courses: module list, lesson count, estimated hours
   - For career: typical job search timeline, skill requirements for the role, portfolio expectations

3. The AI returns a proposed blueprint.

**Step 4: Review & Edit**

The proposed blueprint is shown to the user for confirmation:

```
┌─────────────────────────────────────────────────────┐
│ 📋 Proposed Plan: "Read Atomic Habits"               │
│                                                      │
│ Found: 280 pages, 20 chapters in 4 parts             │
│ Your deadline: May 15 (40 days away)                 │
│ Suggested pace: ~7 pages/day or ~1 chapter every 2   │
│ days                                                 │
│                                                      │
│ Milestones:                                          │
│ ┌──────────────────────────────────────────────────┐ │
│ │ 📍 Part 1: The Fundamentals (Ch 1-3)            │ │
│ │    Target: Apr 12  │  ~40 pages  │  [Edit]      │ │
│ ├──────────────────────────────────────────────────┤ │
│ │ 📍 Part 2: The Four Laws (Ch 4-14)              │ │
│ │    Target: May 2   │  ~160 pages │  [Edit]      │ │
│ ├──────────────────────────────────────────────────┤ │
│ │ 📍 Part 3: Advanced Tactics (Ch 15-17)          │ │
│ │    Target: May 10  │  ~50 pages  │  [Edit]      │ │
│ ├──────────────────────────────────────────────────┤ │
│ │ 📍 Part 4: Wrap-up (Ch 18-20)                   │ │
│ │    Target: May 15  │  ~30 pages  │  [Edit]      │ │
│ └──────────────────────────────────────────────────┘ │
│                                                      │
│ Chapter Breakdown (editable):                        │
│ ┌────┬──────────────────────────┬───────┬──────────┐ │
│ │ #  │ Title                    │ Pages │ Planned  │ │
│ ├────┼──────────────────────────┼───────┼──────────┤ │
│ │ 1  │ The Surprising Power...  │ 14    │ Apr 7    │ │
│ │ 2  │ How Habits Shape...      │ 12    │ Apr 9    │ │
│ │ 3  │ How to Build Better...   │ 14    │ Apr 11   │ │
│ │ 4  │ The Man Who Didn't...    │ 10    │ Apr 13   │ │
│ │ ...│ ...                      │ ...   │ ...      │ │
│ └────┴──────────────────────────┴───────┴──────────┘ │
│                                                      │
│ ⚡ Difficulty notes:                                  │
│ "Chapters 4-14 are the core — densest content.       │
│  Chapters 18-20 are short summary chapters."         │
│                                                      │
│ [Edit any row by clicking it]                        │
│                                                      │
│           [✓ Looks good, activate!]                  │
│           [✏ I want to adjust things]                │
│           [✗ Cancel]                                 │
└─────────────────────────────────────────────────────┘
```

For Career goals, the review looks different:

```
┌─────────────────────────────────────────────────────┐
│ 📋 Proposed Plan: "Get a Junior Web Dev Job"         │
│                                                      │
│ Timeline: 3 months (12 weeks)                        │
│                                                      │
│ Phase 1: Foundation (Weeks 1-3)                      │
│ ┌──────────────────────────────────────────────────┐ │
│ │ ✏ Resume                                        │ │
│ │   • Rewrite with quantified achievements        │ │
│ │   • Tailor for web dev roles                     │ │
│ │   • Get 2 reviews from peers                     │ │
│ │                                                  │ │
│ │ 🔗 LinkedIn                                      │ │
│ │   • Update headline and summary                  │ │
│ │   • Add all projects and skills                  │ │
│ │   • Connect with 20 people in target companies   │ │
│ └──────────────────────────────────────────────────┘ │
│                                                      │
│ Phase 2: Portfolio (Weeks 3-8)                       │
│ ┌──────────────────────────────────────────────────┐ │
│ │ 🛠 Project 1: Personal Portfolio Website         │ │
│ │   5 units: design, build, deploy, write case     │ │
│ │   study, share on LinkedIn                       │ │
│ │                                                  │ │
│ │ 🛠 Project 2: Full-Stack CRUD App                │ │
│ │   6 units: plan, backend, frontend, auth,        │ │
│ │   deploy, write case study                       │ │
│ │                                                  │ │
│ │ 🛠 Project 3: API Integration Project            │ │
│ │   5 units: research APIs, build, polish,         │ │
│ │   deploy, document                               │ │
│ └──────────────────────────────────────────────────┘ │
│                                                      │
│ Phase 3: Job Hunt (Weeks 6-12)                       │
│ ┌──────────────────────────────────────────────────┐ │
│ │ 📨 Applications: 5 per week                      │ │
│ │ 🎤 Interview Prep: 3 sessions per week           │ │
│ │   • Data structures & algorithms                 │ │
│ │   • System design basics                         │ │
│ │   • Behavioral questions (STAR method)           │ │
│ │ 🤝 Networking: 2 outreaches per week             │ │
│ └──────────────────────────────────────────────────┘ │
│                                                      │
│           [✓ Looks good, activate!]                  │
│           [✏ I want to adjust things]                │
│           [✗ Cancel]                                 │
└─────────────────────────────────────────────────────┘
```

Clicking "I want to adjust things" makes all fields editable inline. The user can change dates, reorder units, add/remove items, change estimates.

Clicking "Looks good, activate!" saves the blueprint and all its units/milestones to the database.

---

## Feature 2: AI Research Engine

### How the Research Works

When the wizard triggers research, the system uses **Gemini with web search** to find structured information about the goal.

**Implementation: Use Gemini's built-in search grounding.**

Gemini 2.0 Flash supports a `google_search` tool that lets it search the web during generation. This is different from making separate search API calls — Gemini handles the search internally and incorporates results into its response.

```python
import google.generativeai as genai

model = genai.GenerativeModel(
    "gemini-2.0-flash",
    tools="google_search_retrieval"
)

response = model.generate_content(
    "Find the complete table of contents for the book 'Atomic Habits' by James Clear. "
    "Include chapter numbers, chapter titles, which part they belong to, and approximate page counts."
)
```

If `google_search_retrieval` is not available or doesn't work as expected in the free tier, fall back to a two-step approach:

**Fallback: Manual search + Gemini processing**
1. Use a free search API or scraping to get raw search results
2. Pass the results to Gemini for structured extraction

Since the project already has Gemini set up, try the built-in search tool first. If it fails, ask the user to input the structure manually (the wizard still works, just without auto-research).

### Research Prompts by Goal Type

**For Learning Goals (Books):**
```
Search for the book "{title}" by {author if provided}.

Find and return:
1. Total page count
2. Number of chapters
3. Complete table of contents with:
   - Part/section groupings (if the book has parts)
   - Chapter numbers and titles
   - Approximate page count per chapter (estimate if not available)
4. Any widely noted difficulty spikes (e.g., "Part 2 is much denser")
5. Average reading time estimates

Respond ONLY with valid JSON:
{
  "book_title": "...",
  "author": "...",
  "total_pages": <number>,
  "total_chapters": <number>,
  "parts": [
    {
      "title": "Part 1: ...",
      "chapters": [
        {
          "number": 1,
          "title": "...",
          "estimated_pages": <number>,
          "difficulty": <1.0-3.0 where 1.0 is easy, 3.0 is very dense>,
          "has_exercises": <boolean>,
          "notes": "any relevant notes or null"
        }
      ]
    }
  ],
  "general_notes": "Any overall reading advice or structure notes",
  "estimated_total_hours": <number>,
  "confidence": "high|medium|low"
}

If you cannot find detailed chapter info, set confidence to "low" and estimate based on what you can find. Always provide at least the total page/chapter count.
```

**For Learning Goals (Courses):**
```
Search for the course "{title}" on {platform if mentioned}.

Find and return:
1. Total number of modules/sections/weeks
2. Complete curriculum with:
   - Module/section titles
   - Number of lessons per module
   - Estimated time per module
   - Whether there are assignments, projects, or quizzes
3. Prerequisites
4. Total estimated completion time

Respond ONLY with valid JSON:
{
  "course_title": "...",
  "platform": "...",
  "instructor": "...",
  "total_modules": <number>,
  "total_hours": <number>,
  "modules": [
    {
      "number": 1,
      "title": "...",
      "lessons": <number>,
      "estimated_minutes": <number>,
      "has_assignment": <boolean>,
      "has_project": <boolean>,
      "difficulty": <1.0-3.0>,
      "topics": ["topic1", "topic2"]
    }
  ],
  "prerequisites": ["..."],
  "final_project": "description or null",
  "confidence": "high|medium|low"
}
```

**For Career Goals:**
```
The user wants to achieve this career goal: "{goal_title}"
Timeline: {timeline}
They already have: {checklist of what they have}
They're missing: {checklist of what they don't have}

Research and create a structured job search plan. Consider:
1. What skills/portfolio pieces are typically expected for this role?
2. What does a realistic application timeline look like?
3. What interview preparation is needed?

Respond ONLY with valid JSON:
{
  "role_title": "...",
  "market_assessment": "Brief assessment of the job market for this role",
  "phases": [
    {
      "title": "Phase name",
      "weeks": [<start_week>, <end_week>],
      "focus": "What this phase is about",
      "units": [
        {
          "title": "Specific action item",
          "description": "What exactly to do",
          "estimated_minutes": <number>,
          "type": "resume|linkedin|portfolio|application|interview_prep|networking|skill_gap",
          "difficulty": <1.0-3.0>,
          "dependencies": ["titles of units that must come first"]
        }
      ]
    }
  ],
  "weekly_recurring": {
    "applications_per_week": <number>,
    "interview_prep_sessions": <number>,
    "networking_outreaches": <number>
  },
  "portfolio_suggestions": [
    {
      "title": "Project name",
      "description": "What to build and why it impresses employers",
      "technologies": ["tech1", "tech2"],
      "estimated_days": <number>
    }
  ],
  "skill_gaps": ["skills the user likely needs to develop"],
  "confidence": "high|medium|low"
}
```

---

## Feature 3: Smart Scheduling Engine

### How Scheduling Works

Once a blueprint is confirmed, the system distributes work units across available days.

**Scheduling Algorithm (Python, not AI — this is deterministic):**

```python
def schedule_blueprint(blueprint_id):
    """
    Distribute blueprint units across days from today to deadline.
    
    Algorithm:
    1. Get all pending units and the deadline
    2. Calculate available working days (exclude days based on habit frequency if applicable)
    3. Assign units to days, respecting:
       - Dependencies (unit B after unit A)
       - Difficulty weighting (harder units get their own day, easy units can be grouped)
       - Schedule strategy (even, front_loaded, back_loaded, adaptive)
       - User's day-of-week completion patterns (assign less on weak days)
    4. Save scheduled_date for each unit
    """
    
    blueprint = get_blueprint(blueprint_id)
    units = get_pending_units(blueprint_id)
    deadline = blueprint.goal.deadline
    today = date.today()
    
    available_days = calculate_available_days(today, deadline, blueprint)
    
    if blueprint.schedule_strategy == 'even':
        # Distribute units evenly across available days
        units_per_day = len(units) / len(available_days)
        assign_evenly(units, available_days, units_per_day)
    
    elif blueprint.schedule_strategy == 'front_loaded':
        # More units early, tapering off
        # Useful for "finish early, leave buffer"
        assign_front_loaded(units, available_days)
    
    elif blueprint.schedule_strategy == 'adaptive':
        # Uses day-of-week completion patterns
        # Assigns more units to the user's productive days
        patterns = get_day_of_week_patterns()
        assign_adaptive(units, available_days, patterns)
```

### Rescheduling

When the user falls behind or gets ahead, the system should detect this and offer to reschedule:

- **Trigger**: When a unit's `scheduled_date` passes and it's still 'pending'
- **Action**: The next time the user opens the app or generates a plan, show a banner:
  ```
  📅 You're 2 chapters behind on "Atomic Habits". 
  Want me to adjust the schedule?
  [Reschedule] [I'll catch up] [Pause goal]
  ```
- "Reschedule" re-runs the scheduling algorithm from today with remaining units
- "I'll catch up" does nothing (units stay with past dates, the planner will try to include them)
- "Pause goal" sets the blueprint to 'paused'

---

## Feature 4: Pace Tracking & Adaptive Estimates

### How Pace Tracking Works

Every time a task linked to a blueprint_unit is completed, the system records:
- Which unit was completed
- How long it took (calculated from task estimated_minutes or manually logged)
- The current date/time

This data updates the blueprint's pace estimates:

```python
def update_pace(blueprint_id, unit_id, actual_minutes):
    """
    Update the rolling average pace for this blueprint.
    
    Uses exponential moving average so recent data weighs more:
    new_pace = (old_pace * 0.7) + (actual_minutes * 0.3)
    """
    blueprint = get_blueprint(blueprint_id)
    
    if blueprint.pace_samples == 0:
        blueprint.actual_pace_minutes = actual_minutes
    else:
        blueprint.actual_pace_minutes = (
            blueprint.actual_pace_minutes * 0.7 + actual_minutes * 0.3
        )
    
    blueprint.pace_samples += 1
    blueprint.completed_units += 1
    save_blueprint(blueprint)
```

### How Pace Data Improves Task Generation

The Planner Agent now receives pace data in its context:

```
## Blueprint: "Read Atomic Habits"
AI estimated pace: 20 min/chapter
Your actual pace: 35 min/chapter (based on 5 chapters completed)
Adjustment: tasks should be scoped for ~35 min per chapter, not 20

Today's scheduled units:
- Chapter 9: "The Role of Family and Friends" (est. 35 min based on your pace)
  Pages 121-135, difficulty: 1.5x average

NOTE: At current pace, you'll finish 3 days late. Consider:
- Extending deadline
- Combining shorter chapters on weekends
- Reading during commute
```

---

## Feature 5: Hyper-Specific Task Generation

### What Changes in the Planner Agent

The Planner Agent's prompt now receives detailed blueprint data and generates much more specific tasks.

**Old task output:**
```json
{"title": "Work on Atomic Habits", "description": "Continue reading", "estimated_minutes": 30}
```

**New task output:**
```json
{
  "title": "Read Chapter 9: The Role of Family and Friends (pp. 121-135)",
  "description": "This chapter covers how social environment shapes habits. Take notes on the '2 Minute Rule' concept. After reading, do the reflection exercise on page 134.",
  "estimated_minutes": 35,
  "blueprint_unit_id": 42,
  "specificity_details": {
    "page_range": "121-135",
    "exercises": ["Reflection exercise p.134"],
    "key_concepts": ["social environment", "2 Minute Rule"],
    "chapter_context": "This builds on Chapter 8's discussion of motivation"
  }
}
```

**For career goals:**
```json
{
  "title": "Apply to 3 junior web dev positions on LinkedIn",
  "description": "Focus on companies using React/Node.js stack. Tailor cover letter for each. Log applications in Planwise career tracker.",
  "estimated_minutes": 90,
  "blueprint_unit_id": 78,
  "specificity_details": {
    "target_count": 3,
    "focus_criteria": "React/Node.js stack, companies with <500 employees",
    "template_reference": "Use the cover letter template from Week 1",
    "log_action": "Add each application to career pipeline"
  }
}
```

**For progressive habits:**
```json
{
  "title": "Run 2.5km (Week 3 target)",
  "description": "Increased from 2.0km last week. Keep a comfortable pace — this is about building consistency, not speed.",
  "estimated_minutes": 20,
  "specificity_details": {
    "current_target": 2.5,
    "previous_target": 2.0,
    "unit": "km",
    "progression_note": "Next week: 3.0km",
    "week_number": 3
  }
}
```

### Updated Planner Agent Prompt Additions

Add this section to the Planner Agent's prompt:

```
## Active Blueprints

{for each active blueprint:}

### Blueprint: {title} ({type})
Type: {learning/career/habit}
Deadline: {date} ({days_remaining} days left)
Progress: {completed_units}/{total_units} {unit_label}s ({percentage}%)
Pace: estimated {estimated_pace}min/{unit_label}, actual {actual_pace}min/{unit_label}
Schedule status: {on_track / behind_X_units / ahead_X_units}

Today's scheduled units:
{for each unit scheduled for today:}
  - Unit #{unit_number}: "{title}"
    Description: {description}
    Estimated time: {estimated_minutes}min (adjusted for user's pace)
    Difficulty: {difficulty}x average
    Metadata: {page range, exercises, etc.}
    Depends on: {dependency unit title, if any}
    Status: {pending/in_progress}

{if behind schedule:}
⚠️ Behind by {N} {unit_label}s. Consider:
- Assigning extra units today if workload is light
- Combining shorter units
- Adjusting the deadline

{if habit:}
Habit: {habit_name}
Frequency: {frequency}
Today's target: {current_quantity} {quantity_unit}
Progression: {base} → {current} → {target} ({progression_type})
Streak: {habit_streak} days

## Task Generation Rules for Blueprints

1. For LEARNING blueprints:
   - Reference specific chapters, page ranges, and exercises
   - If a chapter has exercises, create a separate task for them
   - If the user's actual pace is slower than estimated, reduce the scope (1 chapter instead of 2)
   - Include "what to focus on" or "key concepts" when possible

2. For CAREER blueprints:
   - Application tasks: specify how many, what criteria to filter by
   - Portfolio tasks: reference the specific project and current phase
   - Interview prep: specify exact topics (e.g., "Practice 3 binary tree problems")
   - Networking: suggest specific actions (e.g., "Comment on 2 posts by engineers at target companies")

3. For HABIT blueprints:
   - Use the exact current_quantity and quantity_unit
   - If progressive, mention last week's target and next week's target
   - If the user missed yesterday's habit, don't double up — just do today's target
   - Keep the description motivational but brief

4. ALWAYS include the blueprint_unit_id in your response so the system can mark units complete when tasks are done
5. If multiple blueprints have units scheduled today, balance them — don't overload one area
6. Respect dependencies: never schedule a unit whose dependency is incomplete
```

---

## Feature 6: Habit Progression Engine

### How Progressive Habits Work

The scheduler handles habit progression automatically:

```python
def check_habit_progression():
    """
    Run daily (or on relevant days). For each progressive habit:
    1. Check if it's time to increment (based on increment_frequency)
    2. If yes, increase current_quantity by increment_amount
    3. Cap at target_quantity
    4. Update last_increment_date
    """
    for habit in get_progressive_habits():
        if should_increment(habit):
            new_quantity = min(
                habit.current_quantity + habit.increment_amount,
                habit.target_quantity
            )
            update_habit_quantity(habit.id, new_quantity)
```

### Habit in Daily Task Generation

When the Planner generates tasks, for each active habit scheduled today:
- If constant: always generates the same task (e.g., "Meditate for 15 minutes")
- If progressive: generates the task with current_quantity (e.g., "Run 2.5km — increased from 2.0km last week")

The task is linked to the habit's blueprint so completion is tracked.

---

## API Routes

### Goal Setup Wizard

**`POST /api/goals/<id>/research`**
- Triggers AI research for the goal
- Body: `{ "type": "learning|career|habit", "details": { ... } }`
  - For learning: `{ "resource_title": "Atomic Habits", "author": "James Clear", "resource_type": "book" }`
  - For career: `{ "role": "junior web developer", "timeline_weeks": 12, "have": [...], "missing": [...] }`
  - For habit: not needed (habits don't require research)
- Calls Gemini with web search
- Returns the proposed blueprint structure (NOT yet saved to database)
- Response: the full JSON from the research prompt

**`POST /api/goals/<id>/blueprint`**
- Saves the confirmed blueprint
- Body: the full blueprint structure (potentially edited by user)
- Creates entries in `goal_blueprints`, `blueprint_milestones`, `blueprint_units`
- Runs the scheduling algorithm
- Returns the complete blueprint with scheduled dates

**`PUT /api/blueprints/<id>`**
- Update a blueprint's settings (schedule_strategy, estimated_pace, etc.)

**`POST /api/blueprints/<id>/reschedule`**
- Re-runs the scheduling algorithm for remaining pending units from today
- Returns updated schedule

**`GET /api/blueprints/<id>`**
- Full blueprint with milestones, units, and progress stats

### Blueprint Units

**`GET /api/blueprints/<id>/units`**
- List all units with status, scheduled dates, completion data

**`PATCH /api/units/<id>/complete`**
- Mark a unit as completed
- Body: `{ "actual_minutes": 35 }` (optional)
- Updates pace tracking
- Checks if milestone is complete (all units in milestone done)
- Returns updated blueprint progress

**`PATCH /api/units/<id>/skip`**
- Mark a unit as skipped (e.g., user already knows this chapter)

### Career Pipeline

**`GET /api/career/pipeline?blueprint_id=X`**
- List all career pipeline entries for a blueprint

**`POST /api/career/pipeline`**
- Add entry: `{ "blueprint_id": X, "entry_type": "application", "title": "...", "company": "...", "url": "...", "status": "applied" }`

**`PUT /api/career/pipeline/<id>`**
- Update entry (change status, add notes, set follow-up date)

**`GET /api/career/pipeline/stats`**
- Returns: `{ "total_applications": 15, "interviews": 3, "offers": 0, "rejection_rate": "60%", "avg_response_days": 5 }`

### Habits

**`GET /api/habits`**
- List all habit configs with current quantities and streaks

**`PATCH /api/habits/<id>/log`**
- Log today's habit as done
- Body: `{ "actual_quantity": 2.7 }` (optional, for tracking actual vs target)

---

## Frontend Changes

### Goal Card Enhancement

Each goal in the sidebar now shows its blueprint type and progress:

```
── Goals ───────────────────
📅 Yearly:
  📚 Read 12 books
     ████████░░ 8/12 books
     
  💼 Get web dev job
     ███░░░░░░░ Phase 1/3
     
📆 Monthly:
  📚 Read Atomic Habits
     ██████░░░░ 12/20 chapters
     ⚠️ 2 days behind
     
  🔄 Run 5km
     2.5km / 5km target
     🔥 12 day streak
```

- Blueprint type icons: 📚 Learning, 💼 Career, 🔄 Habit
- Mini progress bars inline
- Warning indicators for behind-schedule items
- Clicking opens the detailed blueprint view

### Blueprint Detail View

When clicking a goal with a blueprint, the main content area shows:

**For Learning Blueprints:**
```
┌─────────────────────────────────────────────────────┐
│ 📚 Atomic Habits                     ██████░░░░ 60% │
│ by James Clear                                      │
│ Deadline: May 15 (26 days)    Pace: 35 min/chapter  │
│                                                      │
│ Milestones:                                          │
│ ✅ Part 1: The Fundamentals ─────── completed Apr 11 │
│ 🔵 Part 2: The Four Laws ────────── due May 2       │
│    ████████░░ 6/11 chapters                          │
│ ⬜ Part 3: Advanced Tactics ─────── due May 10       │
│ ⬜ Part 4: Wrap-up ──────────────── due May 15       │
│                                                      │
│ This Week's Units:                                   │
│ ┌──────────────────────────────────────────────────┐ │
│ │ ✅ Ch 9: Role of Family (35min)     completed    │ │
│ │ ✅ Ch 10: Finding Your Habit (40min) completed   │ │
│ │ 🔵 Ch 11: Walk Slowly (est. 35min)  today       │ │
│ │ ⬜ Ch 12: The Goldilocks Rule        Apr 10      │ │
│ │ ⬜ Ch 13: Downside of Habits         Apr 11      │ │
│ └──────────────────────────────────────────────────┘ │
│                                                      │
│ Pace Analysis:                                       │
│ AI estimated: 20 min/chapter                         │
│ Your actual: 35 min/chapter (based on 12 chapters)   │
│ 📈 Pace is consistent — schedule adjusted            │
│                                                      │
│               [Reschedule] [Edit Blueprint]          │
└─────────────────────────────────────────────────────┘
```

**For Career Blueprints:**
```
┌─────────────────────────────────────────────────────┐
│ 💼 Get Junior Web Dev Job            ███░░░░░░░ 30% │
│ Timeline: 12 weeks (8 remaining)                     │
│                                                      │
│ Pipeline:                                            │
│ ┌──────────────────────────────────────────────────┐ │
│ │ Applications:  15 sent │ 3 interviews │ 0 offers │ │
│ │ Response rate: 40%     │ Avg wait: 5 days        │ │
│ └──────────────────────────────────────────────────┘ │
│                                                      │
│ ✅ Phase 1: Foundation ───────── completed            │
│ 🔵 Phase 2: Portfolio ────────── in progress         │
│    ██████░░░░ 2/3 projects done                      │
│    Current: Full-Stack CRUD App (building frontend)  │
│ ⬜ Phase 3: Job Hunt ─────────── starts Week 6       │
│                                                      │
│ Recent Applications:                                 │
│ ┌────────────────────────────────────────────┐       │
│ │ Acme Corp — Junior SWE      Applied 4/1   │       │
│ │ Status: Screening    [Update] [Notes]      │       │
│ ├────────────────────────────────────────────┤       │
│ │ StartupXYZ — Frontend Dev   Applied 3/28  │       │
│ │ Status: Interview scheduled  [Update]      │       │
│ └────────────────────────────────────────────┘       │
│                                                      │
│ [+ Log Application] [+ Add Portfolio Piece]          │
└─────────────────────────────────────────────────────┘
```

**For Habit Blueprints:**
```
┌─────────────────────────────────────────────────────┐
│ 🔄 Running                           🔥 12 days     │
│ Progressive: 2.0km → 5.0km                          │
│                                                      │
│ Current target: 2.5km (+0.5 per week)                │
│ Next increase: April 14 → 3.0km                     │
│                                                      │
│ This Week:                                           │
│ Mon ✅  Tue ✅  Wed ——  Thu 🔵  Fri ——  Sat ——  Sun ——│
│ (scheduled: Tue, Thu, Fri)                           │
│                                                      │
│ Progress:                                            │
│ Week 1: 2.0km ✅                                     │
│ Week 2: 2.0km ✅                                     │
│ Week 3: 2.5km ← you are here                        │
│ Week 4: 3.0km                                       │
│ ...                                                  │
│ Week 7: 5.0km (target!)                              │
│                                                      │
│          [Log Today's Run] [Edit Habit]              │
└─────────────────────────────────────────────────────┘
```

### Wizard Modal

The Goal Setup Wizard from Feature 1 is implemented as a multi-step modal. Each step slides in from the right (simple CSS transition). Steps:
1. Type selection (3 cards)
2. Details form (varies by type)
3. Loading/research screen
4. Review & confirm (editable table)

The modal should be wide (max-width 700px) to accommodate the review table.

### Dashboard Integration

The "Today's Tasks" section now shows blueprint-linked tasks with richer info:

```
☐ 📚 Read Chapter 11: Walk Slowly, but Never Backward
  Atomic Habits │ pp. 141-155 │ ~35min │ ⚡ High energy
  Key concepts: habit stacking, temptation bundling
  
☐ 💼 Apply to 3 junior web dev positions
  Career: Web Dev Job │ Focus: React/Node.js stack │ ~90min
  
☐ 🔄 Run 2.5km (Week 3 target)
  Habit │ ↑ from 2.0km │ ~20min │ 🌿 Low energy
```

---

## Telegram Bot Updates

### New Commands

**`/blueprint <goal_name>`**
- Shows the blueprint summary for a goal:
  ```
  📚 Atomic Habits
  Progress: 12/20 chapters (60%)
  Pace: 35 min/chapter
  Schedule: 2 days behind
  
  Today: Ch 11 "Walk Slowly" (pp. 141-155)
  Tomorrow: Ch 12 "The Goldilocks Rule"
  ```

**`/career`**
- Shows career pipeline summary:
  ```
  💼 Job Search Pipeline
  
  📨 Applications: 15 sent
  📞 Interviews: 3
  ✅ Offers: 0
  
  Recent:
  • Acme Corp (Screening)
  • StartupXYZ (Interview 4/10)
  
  Use /apply to log a new application
  ```

**`/apply`**
- Quick-add a job application:
  ```
  📝 Log Application
  
  Send me the details in this format:
  Company, Role, URL (optional)
  
  Example: Google, Junior SWE, https://careers.google.com/xyz
  ```

**`/habit`**
- Shows today's habit status:
  ```
  🔄 Today's Habits
  
  🏃 Running: 2.5km target
     [✓ Done] [Skip today]
  
  🧘 Meditation: 15min
     [✓ Done] [Skip today]
  ```

---

## Integration with Existing Agents

### Research Agent Update

The Research Agent from Phase 5 now uses blueprint data instead of just `learning_resources`. It's aware of:
- Scheduled units for today
- Pace tracking data
- Behind/ahead schedule status
- Difficulty ratings per unit

### Accountability Agent Update

The Accountability Agent now tracks:
- Blueprint adherence (how often does the user complete scheduled units on time?)
- Habit streaks and breaks
- Career pipeline velocity (applications per week trending up or down?)
- Pace trends (is the user getting faster or slower?)

New insight types:
- "You've completed every scheduled chapter on time for 2 weeks — your pace estimate is now very accurate"
- "Your application rate dropped from 5/week to 2/week. Time to ramp back up?"
- "You've skipped running 3 times this week — consider whether Tue/Thu/Fri is realistic or if you need different days"

---

## Error Handling

- If Gemini web search fails during research: show an error and offer manual input mode (user types in the structure themselves)
- If the research returns low-confidence data: show a warning "The AI couldn't find detailed info. Please review and edit the structure."
- If a blueprint has 0 remaining units but the goal isn't marked complete: prompt the user to mark it complete
- If pace tracking has fewer than 3 samples: show "estimated" instead of "your pace" and note that it's still learning
- If the user tries to schedule more work than available days: warn them and suggest extending the deadline or reducing scope

---

## Implementation Order

1. **Database tables** — Create all new tables, add `blueprint_unit_id` to `daily_tasks`. Run migrations safely with IF NOT EXISTS and try/except for ALTER TABLE.

2. **Blueprint CRUD** — `goal_blueprints`, `blueprint_milestones`, `blueprint_units` CRUD operations in `database.py`. API routes for creating, reading, updating blueprints.

3. **AI Research Engine** — Implement the Gemini web search calls for books, courses, and career goals. Test with 3-4 real examples. Handle fallbacks.

4. **Goal Setup Wizard UI** — The multi-step modal: type selection → details → research loading → review/edit → confirm. Wire up to the research API.

5. **Scheduling Engine** — The Python scheduling algorithm. Distribute units across days. Implement reschedule endpoint.

6. **Pace Tracking** — Hook into task completion to update pace. Calculate rolling averages. Show pace data in blueprint views.

7. **Habit System** — `habit_config` table, progression engine, habit-specific task generation, daily logging.

8. **Career Pipeline** — `career_pipeline` table, CRUD routes, pipeline UI with application tracking.

9. **Planner Agent Update** — Update the prompt with blueprint context, generate hyper-specific tasks with `blueprint_unit_id` references.

10. **Blueprint Detail Views** — Full detail views for learning, career, and habit blueprints.

11. **Telegram Updates** — New commands: `/blueprint`, `/career`, `/apply`, `/habit`.

12. **Agent Updates** — Update Research and Accountability agents to use blueprint data.

13. **Polish** — Reschedule banners, behind-schedule warnings, pace confidence indicators, edge cases.

## Important Notes

- Blueprints are OPTIONAL. Existing goals without blueprints continue to work exactly as before. The planner simply has less context for those goals and generates less specific tasks.
- The wizard should feel lightweight, not bureaucratic. The user fills in one text field and a deadline, clicks "Research", reviews the result, and confirms. Total time: under 2 minutes.
- Web search during research costs API quota. Cache research results in `source_info` so the user can re-view them without re-searching.
- The scheduling algorithm is pure Python — no AI calls. It should be fast and deterministic. AI is used for research and task generation, not for scheduling math.
- Pace tracking needs at least 3 data points before it starts adjusting estimates. Before that, use the AI's initial estimates.
- For career goals, the pipeline tracker is a simple CRUD feature, not an AI feature. The AI uses pipeline data as context for task generation, but the tracker itself is just a database table with a UI.
- Habit progression should be gentle. If the user misses 3+ days in a row, pause the progression (don't increase the target while they're struggling to meet the current one).
- Keep the total API calls reasonable. The wizard research is a one-time cost per goal. Daily task generation should not make additional API calls beyond what the existing agents already do — the blueprint data is just richer context in the same prompts.
