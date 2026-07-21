"""Task persistence helpers — thin wrappers over session_scope.

Handlers/jobs call these instead of touching the ORM directly. Returned Task objects
are safe to read after the call (see expire_on_commit in db.session_scope).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlmodel import select

from .db import session_scope
from .models import Task


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_task(
    *,
    title: str,
    raw_text: str,
    iso_week: str,
    project: str | None = None,
    priority: str = "P2",
    status: str = "inbox",
    due_date: date | None = None,
    scheduled_for: date | None = None,
    source: str = "tg",
    airtable_id: str | None = None,
) -> Task:
    task = Task(
        title=title,
        raw_text=raw_text,
        iso_week=iso_week,
        project=project,
        priority=priority,
        status=status,
        due_date=due_date,
        scheduled_for=scheduled_for,
        source=source,
        airtable_id=airtable_id,
    )
    with session_scope() as s:
        s.add(task)
        s.flush()  # populate task.id
    return task


def get_task(task_id: int) -> Task | None:
    with session_scope() as s:
        return s.get(Task, task_id)


def update_task(task_id: int, **fields) -> Task | None:
    with session_scope() as s:
        task = s.get(Task, task_id)
        if task is None:
            return None
        for key, value in fields.items():
            setattr(task, key, value)
        task.updated_at = _now()
        s.add(task)
        s.flush()
        return task


def delete_task(task_id: int) -> bool:
    with session_scope() as s:
        task = s.get(Task, task_id)
        if task is None:
            return False
        s.delete(task)
        return True


def list_by_status(status: str) -> list[Task]:
    with session_scope() as s:
        return list(s.exec(select(Task).where(Task.status == status)))


def list_active() -> list[Task]:
    """All tasks that aren't done — candidates for NL edits."""
    with session_scope() as s:
        return list(s.exec(select(Task).where(Task.status != "done")))


def count_by_status(status: str) -> int:
    with session_scope() as s:
        return len(list(s.exec(select(Task).where(Task.status == status))))
