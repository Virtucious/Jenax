"""
Blueprint Scheduling Engine — Phase 6

Pure Python, deterministic. No AI calls.
Distributes blueprint units across available days from today to deadline.
"""

from datetime import date, timedelta

import database as db


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _available_days(start: date, end: date) -> list[date]:
    days = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _topological_order(units: list[dict]) -> list[dict]:
    """Return units ordered so that each unit comes after its dependency."""
    id_map = {u["id"]: u for u in units}
    ordered: list[dict] = []
    visited: set[int] = set()

    def visit(unit: dict):
        if unit["id"] in visited:
            return
        dep_id = unit.get("depends_on")
        if dep_id and dep_id in id_map:
            visit(id_map[dep_id])
        visited.add(unit["id"])
        ordered.append(unit)

    for u in units:
        visit(u)
    return ordered


def _effective_minutes(unit: dict, default_pace: float) -> float:
    base = unit.get("estimated_minutes") or default_pace
    diff = unit.get("difficulty") or 1.0
    return base * diff


def _assign_with_budgets(units: list[dict], days: list[date], budgets: list[float]):
    """Assign scheduled_date to each unit given per-day minute budgets."""
    day_idx = 0
    day_spent = 0.0
    for unit in units:
        if day_idx >= len(days):
            day_idx = len(days) - 1
        unit["_scheduled_date"] = days[day_idx]
        day_spent += unit["_eff_min"]
        if day_spent >= budgets[day_idx] and day_idx < len(days) - 1:
            day_idx += 1
            day_spent = 0.0


def _even_budgets(total_minutes: float, num_days: int) -> list[float]:
    daily = total_minutes / num_days if num_days else total_minutes
    return [daily] * num_days


def _front_loaded_budgets(total_minutes: float, num_days: int) -> list[float]:
    # weight falls from 2.0 → 0.5 linearly
    weights = [2.0 - 1.5 * i / max(num_days - 1, 1) for i in range(num_days)]
    total_w = sum(weights)
    return [(w / total_w) * total_minutes for w in weights]


def _back_loaded_budgets(total_minutes: float, num_days: int) -> list[float]:
    weights = [0.5 + 1.5 * i / max(num_days - 1, 1) for i in range(num_days)]
    total_w = sum(weights)
    return [(w / total_w) * total_minutes for w in weights]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def schedule_blueprint(blueprint_id: int) -> bool:
    """
    Assign scheduled_date to all pending units in a blueprint.
    Called once after the wizard confirms a blueprint.
    Returns True on success, False if blueprint not found.
    """
    return _run_schedule(blueprint_id, pending_only=False)


def reschedule_blueprint(blueprint_id: int) -> bool:
    """
    Re-distribute remaining pending units from today to the deadline.
    Uses actual_pace_minutes instead of estimated_pace_minutes when available.
    """
    return _run_schedule(blueprint_id, pending_only=True)


def _run_schedule(blueprint_id: int, pending_only: bool) -> bool:
    blueprint = db.get_blueprint(blueprint_id)
    if not blueprint:
        return False

    goal = db.get_goal(blueprint["goal_id"])
    today = date.today()

    if goal and goal.get("deadline"):
        try:
            deadline = date.fromisoformat(goal["deadline"])
        except ValueError:
            deadline = today + timedelta(days=30)
        if deadline < today:
            deadline = today + timedelta(days=30)
    else:
        deadline = today + timedelta(days=30)

    days = _available_days(today, deadline)
    if not days:
        return False

    status_filter = ["pending"] if pending_only else ["pending", "in_progress"]
    units = db.get_blueprint_units(blueprint_id, status_filter=status_filter)
    if not units:
        return True

    # Use actual pace if we have enough samples, otherwise estimated
    if (blueprint.get("pace_samples") or 0) >= 3 and blueprint.get("actual_pace_minutes"):
        default_pace = blueprint["actual_pace_minutes"]
    else:
        default_pace = blueprint.get("estimated_pace_minutes") or 30.0

    units = _topological_order(units)
    for u in units:
        u["_eff_min"] = _effective_minutes(u, default_pace)

    total_minutes = sum(u["_eff_min"] for u in units)
    num_days = len(days)
    strategy = blueprint.get("schedule_strategy", "even")

    if strategy == "front_loaded":
        budgets = _front_loaded_budgets(total_minutes, num_days)
    elif strategy == "back_loaded":
        budgets = _back_loaded_budgets(total_minutes, num_days)
    else:
        budgets = _even_budgets(total_minutes, num_days)

    _assign_with_budgets(units, days, budgets)

    conn = db.get_connection()
    with conn:
        for unit in units:
            if "_scheduled_date" in unit:
                conn.execute(
                    "UPDATE blueprint_units SET scheduled_date = ? WHERE id = ?",
                    (unit["_scheduled_date"].isoformat(), unit["id"]),
                )
    conn.close()
    return True
