"""Task persistence helpers — thin wrappers over session_scope.

Handlers/jobs call these instead of touching the ORM directly. Returned Task objects
are safe to read after the call (see expire_on_commit in db.session_scope).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlmodel import select

from .db import session_scope
from .models import Setting, Task


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


def last_touched_active() -> Task | None:
    """Most recently created/updated task that isn't done — the 'эту задачу' fallback."""
    with session_scope() as s:
        return s.exec(
            select(Task).where(Task.status != "done").order_by(Task.updated_at.desc())
        ).first()


def list_active() -> list[Task]:
    """All tasks that aren't done — candidates for NL edits."""
    with session_scope() as s:
        return list(s.exec(select(Task).where(Task.status != "done")))


def count_by_status(status: str) -> int:
    with session_scope() as s:
        return len(list(s.exec(select(Task).where(Task.status == status))))


# --- Airtable mirroring support -------------------------------------------

def get_by_airtable_id(airtable_id: str) -> Task | None:
    with session_scope() as s:
        return s.exec(select(Task).where(Task.airtable_id == airtable_id)).first()


def set_airtable_id(task_id: int, airtable_id: str) -> None:
    """Attach an Airtable record id WITHOUT bumping updated_at (avoids resync loop)."""
    with session_scope() as s:
        task = s.get(Task, task_id)
        if task is not None:
            task.airtable_id = airtable_id
            s.add(task)


def tasks_to_mirror(since: datetime | None) -> list[Task]:
    """Tasks needing a push out: never-mirrored, or changed since last sync."""
    with session_scope() as s:
        stmt = select(Task)
        if since is not None:
            stmt = stmt.where((Task.airtable_id.is_(None)) | (Task.updated_at > since))
        return list(s.exec(stmt))


# --- Setting kv ------------------------------------------------------------

def get_setting(key: str) -> str | None:
    with session_scope() as s:
        row = s.get(Setting, key)
        return row.value if row else None


def set_setting(key: str, value: str) -> None:
    with session_scope() as s:
        row = s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value=value))
        else:
            row.value = value
            s.add(row)
