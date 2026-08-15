"""The rule of 5 — selecting at most five tasks for 'today'.

Selection (see docs/DATA_MODEL.md):
  1. everything with status == 'today', plus
  2. everything with scheduled_for == today (surfaced for this day), plus
  3. every overdue task (due_date < today, not done).

No silent top-up from undated inbox — capture stays in backlog until the user
says «на сегодня» / presses the triage button, or the scheduled day arrives.

Tasks with scheduled_for > today stay in backlog until that day.

materialize_today() promotes inbox commitments (scheduled today / overdue) to
status=today so they leave the backlog (one place at a time).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlmodel import select

from . import store
from .db import session_scope
from .models import Task

LIMIT = 5
_PRIORITY_RANK = {"P1": 0, "P2": 1, "P3": 2}
_FAR_FUTURE = date.max
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _is_overdue(task: Task, today: date) -> bool:
    return task.due_date is not None and task.due_date < today


def _scheduled_today(task: Task, today: date) -> bool:
    return task.scheduled_for is not None and task.scheduled_for == today


def _order_key(task: Task, today: date):
    return (
        0 if _is_overdue(task, today) else 1,
        _PRIORITY_RANK.get(task.priority, 1),
        task.due_date or _FAR_FUTURE,
        task.created_at or _EPOCH,
    )


def choose(tasks: list[Task], today: date) -> list[Task]:
    """Pure selection over an in-memory list (no inbox top-up)."""
    active = [t for t in tasks if t.status != "done"]

    selected: dict[int, Task] = {}
    for t in active:
        if t.status == "today" or _scheduled_today(t, today) or _is_overdue(t, today):
            selected[id(t)] = t

    ordered = sorted(selected.values(), key=lambda t: _order_key(t, today))
    return ordered[:LIMIT]


def select_today(today: date, *, materialize: bool = True) -> list[Task]:
    """DB-backed selection. Optionally promote inbox commitments to status=today."""
    with session_scope() as s:
        tasks = list(s.exec(select(Task).where(Task.status != "done")))
    chosen = choose(tasks, today)
    if materialize:
        materialize_today(chosen)
        # Re-fetch so callers see updated status.
        ids = [t.id for t in chosen if t.id is not None]
        if not ids:
            return []
        return [t for tid in ids if (t := store.get_task(tid)) is not None]
    return chosen


def materialize_today(tasks: list[Task]) -> int:
    """Promote selected inbox tasks to status=today. Returns how many updated."""
    n = 0
    for t in tasks:
        if t.id is None or t.status != "inbox":
            continue
        store.update_task(t.id, status="today")
        n += 1
    return n
