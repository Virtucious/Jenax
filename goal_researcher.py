"""Goal Research Engine — Phase 6

Uses Gemini with Google Search grounding to find goal structure and returns
a proposed blueprint ready for user review. No DB writes happen here.
"""

import json
import re

from google import genai
from google.genai import types

from config import GEMINI_API_KEY

_RESEARCH_MODEL = "gemini-3-flash-preview"


def _client():
    return genai.Client(api_key=GEMINI_API_KEY)


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _call_gemini(prompt: str, use_search: bool = True) -> dict:
    """Call Gemini, optionally with Google Search grounding. Falls back to plain call."""
    client = _client()
    if use_search:
        try:
            response = client.models.generate_content(
                model=_RESEARCH_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                ),
            )
            return _parse_json(response.text)
        except Exception:
            pass  # fall through to plain call
    response = client.models.generate_content(model=_RESEARCH_MODEL, contents=prompt)
    return _parse_json(response.text)


# ---------------------------------------------------------------------------
# Research functions
# ---------------------------------------------------------------------------

def _research_book(title: str, author: str | None) -> dict:
    prompt = f"""Search for the book "{title}"{f' by {author}' if author else ''}.

Find and return:
1. Total page count
2. Number of chapters
3. Complete table of contents: part/section groupings, chapter numbers, titles, approximate page counts
4. Any widely noted difficulty spikes or dense sections
5. Average reading time estimates

Respond ONLY with valid JSON matching this exact structure:
{{
  "book_title": "...",
  "author": "...",
  "total_pages": 0,
  "total_chapters": 0,
  "parts": [
    {{
      "title": "Part 1: ...",
      "chapters": [
        {{"number": 1, "title": "...", "estimated_pages": 0, "difficulty": 1.0, "has_exercises": false, "notes": null}}
      ]
    }}
  ],
  "general_notes": "...",
  "estimated_total_hours": 0,
  "confidence": "high"
}}

If a book has no explicit parts, put all chapters in one part titled "All Chapters".
difficulty scale: 1.0 = easy read, 2.0 = moderately dense, 3.0 = very technical/dense.
confidence: "high" if you found real data, "medium" if estimated, "low" if mostly guessing."""
    return _call_gemini(prompt)


def _research_course(title: str, platform: str | None) -> dict:
    prompt = f"""Search for the course "{title}"{f' on {platform}' if platform else ''}.

Find and return the complete curriculum with modules, lesson counts, and time estimates.

Respond ONLY with valid JSON:
{{
  "course_title": "...",
  "platform": "...",
  "instructor": "...",
  "total_modules": 0,
  "total_hours": 0,
  "modules": [
    {{
      "number": 1,
      "title": "...",
      "lessons": 0,
      "estimated_minutes": 60,
      "has_assignment": false,
      "has_project": false,
      "difficulty": 1.0,
      "topics": []
    }}
  ],
  "prerequisites": [],
  "final_project": null,
  "confidence": "high"
}}"""
    return _call_gemini(prompt)


def _research_career(role: str, timeline_weeks: int, have: list, missing: list) -> dict:
    have_str = ", ".join(have) if have else "nothing yet"
    missing_str = ", ".join(missing) if missing else "everything"
    prompt = f"""Career goal: get a job as "{role}".
Timeline: {timeline_weeks} weeks.
User already has: {have_str}.
User is missing: {missing_str}.

Research this role and create a structured job search plan with concrete phases and action items.

Respond ONLY with valid JSON:
{{
  "role_title": "...",
  "market_assessment": "1-2 sentence assessment of the job market for this role",
  "phases": [
    {{
      "title": "Phase name",
      "weeks": [1, 3],
      "focus": "What this phase is about",
      "units": [
        {{
          "title": "Specific action item",
          "description": "Exactly what to do",
          "estimated_minutes": 60,
          "type": "resume|linkedin|portfolio|application|interview_prep|networking|skill_gap",
          "difficulty": 1.0
        }}
      ]
    }}
  ],
  "weekly_recurring": {{
    "applications_per_week": 5,
    "interview_prep_sessions": 3,
    "networking_outreaches": 2
  }},
  "portfolio_suggestions": [
    {{
      "title": "Project name",
      "description": "What to build and why it impresses employers",
      "technologies": [],
      "estimated_days": 5
    }}
  ],
  "skill_gaps": [],
  "confidence": "high"
}}"""
    return _call_gemini(prompt)


# ---------------------------------------------------------------------------
# Blueprint builders — convert raw research data to save-ready structure
# ---------------------------------------------------------------------------

def _book_to_blueprint(data: dict) -> dict:
    milestones, units = [], []
    unit_number = 1
    total_pages = data.get("total_pages") or 200
    total_chapters = data.get("total_chapters") or 10
    avg_pages = total_pages / max(total_chapters, 1)
    min_per_page = 2.5

    for ms_idx, part in enumerate(data.get("parts", [])):
        milestones.append({"title": part["title"], "sort_order": ms_idx})
        for ch in part.get("chapters", []):
            pages = ch.get("estimated_pages") or avg_pages
            difficulty = ch.get("difficulty") or 1.0
            est_min = max(15, int(pages * min_per_page * difficulty))
            notes = ch.get("notes") or ""
            if ch.get("has_exercises"):
                notes = (notes + " Includes exercises.").strip()
            units.append({
                "unit_number": unit_number,
                "title": f"Ch {ch['number']}: {ch['title']}",
                "description": notes or None,
                "estimated_minutes": est_min,
                "difficulty": difficulty,
                "milestone_index": ms_idx,
                "metadata": {
                    "pages": int(pages),
                    "chapter_number": ch["number"],
                    "has_exercises": bool(ch.get("has_exercises")),
                },
            })
            unit_number += 1

    return {
        "blueprint_type": "learning",
        "title": data.get("book_title", "Book"),
        "source_info": data,
        "unit_label": "chapter",
        "estimated_pace_minutes": max(15, int(avg_pages * min_per_page)),
        "milestones": milestones,
        "units": units,
        "confidence": data.get("confidence", "medium"),
        "general_notes": data.get("general_notes"),
    }


def _course_to_blueprint(data: dict) -> dict:
    modules = data.get("modules", [])
    total_hours = data.get("total_hours") or (len(modules) * 1.5)
    phase_size = max(3, len(modules) // 4 + 1)
    milestones, units = [], []

    for i, mod in enumerate(modules):
        phase_idx = i // phase_size
        if i % phase_size == 0:
            end_mod = min(i + phase_size, len(modules))
            milestones.append({
                "title": f"Phase {phase_idx + 1}: Modules {i+1}–{end_mod}",
                "sort_order": phase_idx,
            })
        units.append({
            "unit_number": i + 1,
            "title": f"Module {mod['number']}: {mod['title']}",
            "estimated_minutes": mod.get("estimated_minutes") or 60,
            "difficulty": mod.get("difficulty") or 1.0,
            "milestone_index": phase_idx,
            "metadata": {"lessons": mod.get("lessons"), "topics": mod.get("topics", [])},
        })

    avg_min = int(total_hours * 60 / len(modules)) if modules else 60
    return {
        "blueprint_type": "learning",
        "title": data.get("course_title", "Course"),
        "source_info": data,
        "unit_label": "module",
        "estimated_pace_minutes": avg_min,
        "milestones": milestones,
        "units": units,
        "confidence": data.get("confidence", "medium"),
    }


def _career_to_blueprint(data: dict) -> dict:
    milestones, units, unit_number = [], [], 1
    for ms_idx, phase in enumerate(data.get("phases", [])):
        milestones.append({
            "title": phase["title"],
            "description": phase.get("focus"),
            "sort_order": ms_idx,
        })
        for u in phase.get("units", []):
            units.append({
                "unit_number": unit_number,
                "title": u["title"],
                "description": u.get("description"),
                "estimated_minutes": u.get("estimated_minutes") or 60,
                "difficulty": u.get("difficulty") or 1.0,
                "milestone_index": ms_idx,
                "metadata": {"type": u.get("type")},
            })
            unit_number += 1

    return {
        "blueprint_type": "career",
        "title": data.get("role_title", "Career Goal"),
        "source_info": data,
        "unit_label": "task",
        "estimated_pace_minutes": 60,
        "milestones": milestones,
        "units": units,
        "confidence": data.get("confidence", "medium"),
        "market_assessment": data.get("market_assessment"),
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def research_and_build(goal_type: str, goal_id: int, details: dict, deadline: str | None) -> dict:
    """
    Research a goal and return a proposed blueprint.

    Returns:
        {
          "research_data": <raw AI research or None for habits>,
          "blueprint": <blueprint dict ready for POST /api/goals/<id>/blueprint>
        }
    """
    if goal_type == "learning":
        resource_type = details.get("resource_type", "book")
        title = details.get("resource_title", "")
        author = details.get("author")
        if resource_type == "course":
            data = _research_course(title, details.get("platform"))
            blueprint = _course_to_blueprint(data)
        else:
            data = _research_book(title, author)
            blueprint = _book_to_blueprint(data)
        return {"research_data": data, "blueprint": blueprint}

    if goal_type == "career":
        data = _research_career(
            role=details.get("role", ""),
            timeline_weeks=int(details.get("timeline_weeks", 12)),
            have=details.get("have", []),
            missing=details.get("missing", []),
        )
        blueprint = _career_to_blueprint(data)
        return {"research_data": data, "blueprint": blueprint}

    if goal_type == "habit":
        hc = details.get("habit_config", {})
        return {
            "research_data": None,
            "blueprint": {
                "blueprint_type": "habit",
                "title": details.get("habit_name", "Habit"),
                "source_info": None,
                "unit_label": "session",
                "estimated_pace_minutes": hc.get("estimated_minutes") or 20,
                "milestones": [],
                "units": [],
                "habit_config": hc,
                "confidence": "high",
            },
        }

    raise ValueError(f"Unknown goal_type: {goal_type!r}")
