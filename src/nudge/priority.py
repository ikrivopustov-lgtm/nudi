"""The rule of 5 — selecting at most five tasks for 'today'.

Selection (see docs/DATA_MODEL.md):
  1. everything with status == 'today', plus
  2. every overdue task (due_date < today, not done), plus
  3. top-up by priority P1 -> P2 -> P3 until we reach 5.

Ordering: overdue first, then priority, then due_date (nulls last), then created_at.
Hard cap of 5.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlmodel import select

from .db import session_scope
from .models import Task

LIMIT = 5
_PRIORITY_RANK = {"P1": 0, "P2": 1, "P3": 2}
_FAR_FUTURE = date.max
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _is_overdue(task: Task, today: date) -> bool:
    return task.due_date is not None and task.due_date < today


def _order_key(task: Task, today: date):
    return (
        0 if _is_overdue(task, today) else 1,
        _PRIORITY_RANK.get(task.priority, 1),
        task.due_date or _FAR_FUTURE,
        task.created_at or _EPOCH,
    )


def choose(tasks: list[Task], today: date) -> list[Task]:
    """Pure selection over an in-memory list. Ignores done/someday for top-up."""
    active = [t for t in tasks if t.status != "done"]

    selected: dict[int, Task] = {}
    for t in active:
        if t.status == "today" or _is_overdue(t, today):
            selected[id(t)] = t

    if len(selected) < LIMIT:
        pool = [
            t
            for t in active
            if id(t) not in selected and t.status not in ("done", "someday")
        ]
        pool.sort(key=lambda t: _order_key(t, today))
        for t in pool:
            if len(selected) >= LIMIT:
                break
            selected[id(t)] = t

    ordered = sorted(selected.values(), key=lambda t: _order_key(t, today))
    return ordered[:LIMIT]


def select_today(today: date) -> list[Task]:
    """DB-backed selection: fetch active tasks and apply `choose`."""
    with session_scope() as s:
        tasks = list(s.exec(select(Task).where(Task.status != "done")))
    return choose(tasks, today)
