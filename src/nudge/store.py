"""Task persistence helpers — thin wrappers over session_scope.

Handlers/jobs call these instead of touching the ORM directly. Returned Task objects
are safe to read after the call (see expire_on_commit in db.session_scope).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from sqlmodel import select

from .db import session_scope
from .models import ActionLog, ConvTurn, Setting, Task


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
    remind_at: datetime | None = None,
    recurrence: str | None = None,
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
        remind_at=remind_at,
        recurrence=recurrence,
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


def search_tasks(query: str, *, include_done: bool = False) -> list[Task]:
    """Substring search over title/project/raw_text."""
    q = f"%{query.lower()}%"
    with session_scope() as s:
        stmt = select(Task)
        if not include_done:
            stmt = stmt.where(Task.status != "done")
        rows = list(s.exec(stmt))
    return [
        t for t in rows
        if query.lower() in f"{t.title} {t.project or ''} {t.raw_text}".lower()
    ]


def completed_since(since: datetime) -> list[Task]:
    since_naive = since.replace(tzinfo=None) if since.tzinfo else since
    with session_scope() as s:
        return list(
            s.exec(
                select(Task)
                .where(Task.completed_at.is_not(None), Task.completed_at >= since_naive)
                .order_by(Task.completed_at.desc())
            )
        )


def list_completed_between(
    since: datetime,
    until: datetime | None = None,
) -> list[Task]:
    """Tasks closed in [since, until). until defaults to now (UTC, naive)."""
    since_naive = since.replace(tzinfo=None) if since.tzinfo else since
    until_naive = (
        until.replace(tzinfo=None)
        if until and until.tzinfo
        else (until or datetime.now(timezone.utc).replace(tzinfo=None))
    )
    with session_scope() as s:
        return list(
            s.exec(
                select(Task)
                .where(
                    Task.completed_at.is_not(None),
                    Task.completed_at >= since_naive,
                    Task.completed_at < until_naive,
                )
                .order_by(Task.completed_at.desc())
            )
        )


# --- reminders -------------------------------------------------------------

def tasks_with_future_reminders(now: datetime) -> list[Task]:
    now = now.replace(tzinfo=None)  # remind_at is stored naive-UTC
    with session_scope() as s:
        return list(
            s.exec(select(Task).where(Task.remind_at.is_not(None), Task.remind_at > now))
        )


# --- conversation memory ---------------------------------------------------

def add_turn(role: str, content: str, *, keep: int = 24) -> None:
    """Append a turn and prune to the most recent `keep`."""
    with session_scope() as s:
        s.add(ConvTurn(role=role, content=content))
        s.flush()
        rows = list(s.exec(select(ConvTurn).order_by(ConvTurn.id.desc())))
        for old in rows[keep:]:
            s.delete(old)


def recent_turns(limit: int = 12) -> list[tuple[str, str]]:
    """Return the last `limit` turns oldest-first as (role, content)."""
    with session_scope() as s:
        rows = list(s.exec(select(ConvTurn).order_by(ConvTurn.id.desc()).limit(limit)))
    rows.reverse()
    return [(r.role, r.content) for r in rows]


# --- undo / action journal -------------------------------------------------

_SNAPSHOT_FIELDS = (
    "title", "raw_text", "project", "iso_week", "priority", "status",
    "due_date", "scheduled_for", "remind_at", "recurrence", "completed_at",
    "source", "airtable_id",
)


def snapshot(task: Task) -> str:
    data = {}
    for f in _SNAPSHOT_FIELDS:
        v = getattr(task, f)
        if isinstance(v, (date, datetime)):
            v = v.isoformat()
        data[f] = v
    data["id"] = task.id
    return json.dumps(data, ensure_ascii=False)


def next_turn() -> int:
    """A fresh turn id for one user message, so undo can revert the whole message."""
    with session_scope() as s:
        rows = list(s.exec(select(ActionLog.turn).order_by(ActionLog.turn.desc()).limit(1)))
    return (rows[0] + 1) if rows else 1


def log_action(kind: str, *, task_id: int | None, before: str | None, summary: str, turn: int = 0) -> None:
    with session_scope() as s:
        s.add(ActionLog(kind=kind, task_id=task_id, before=before, summary=summary, turn=turn))


def _last_undoable_turn() -> list[ActionLog]:
    """All actions of the most recent turn that still has anything to undo, newest first."""
    with session_scope() as s:
        turns = list(
            s.exec(
                select(ActionLog.turn)
                .where(ActionLog.undone == False)  # noqa: E712
                .order_by(ActionLog.turn.desc())
                .limit(1)
            )
        )
        if not turns:
            return []
        return list(
            s.exec(
                select(ActionLog)
                .where(ActionLog.turn == turns[0], ActionLog.undone == False)  # noqa: E712
                .order_by(ActionLog.id.desc())
            )
        )


def _mark_undone(log_id: int) -> None:
    with session_scope() as s:
        row = s.get(ActionLog, log_id)
        if row is not None:
            row.undone = True
            s.add(row)


def _coerce(field: str, value):
    if value is None:
        return None
    if field in ("due_date", "scheduled_for"):
        return date.fromisoformat(value)
    if field in ("remind_at", "completed_at"):
        return datetime.fromisoformat(value)
    return value


def _reverse_one(log: ActionLog) -> None:
    if log.kind == "create" and log.task_id is not None:
        delete_task(log.task_id)
    elif log.kind == "delete" and log.before:
        data = json.loads(log.before)
        with session_scope() as s:
            task = Task(**{f: _coerce(f, data.get(f)) for f in _SNAPSHOT_FIELDS})
            task.id = data.get("id")
            s.add(task)
    elif log.kind == "update" and log.before and log.task_id is not None:
        data = json.loads(log.before)
        with session_scope() as s:
            task = s.get(Task, log.task_id)
            if task is not None:
                for f in _SNAPSHOT_FIELDS:
                    setattr(task, f, _coerce(f, data.get(f)))
                s.add(task)
    _mark_undone(log.id)


def undo_last() -> str | None:
    """Reverse the whole most-recent turn (all its actions). Returns a summary or None."""
    logs = _last_undoable_turn()
    if not logs:
        return None
    for log in logs:  # newest-first so reversals unwind cleanly
        _reverse_one(log)
    # summarise: the primary (oldest) action of the turn, plus a count if several
    primary = logs[-1].summary
    if len(logs) > 1:
        return f"{primary} (и ещё {len(logs) - 1})"
    return primary


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
