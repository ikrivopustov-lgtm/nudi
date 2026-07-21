"""SQLModel tables — the single source of truth lives here.

Field whitelists (also enforced when validating LLM output):
  priority ∈ {P1, P2, P3}
  status   ∈ {inbox, today, done, someday}
  source   ∈ {tg, forward, airtable}
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlmodel import Field, SQLModel

PRIORITIES = ("P1", "P2", "P3")
STATUSES = ("inbox", "today", "done", "someday")
SOURCES = ("tg", "forward", "airtable")

# Priority shown to the user as a colour, not a code.
PRIORITY_EMOJI = {"P1": "🔴", "P2": "🟠", "P3": "🟡"}
PRIORITY_LABEL = {"P1": "🔴 срочно", "P2": "🟠 обычный", "P3": "🟡 потом"}


def priority_dot(priority: str) -> str:
    return PRIORITY_EMOJI.get(priority, "⚪️")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Task(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    raw_text: str
    project: str | None = Field(default=None, index=True)
    iso_week: str = Field(index=True)          # e.g. "2026-W30"
    priority: str = Field(default="P2", index=True)   # P1 | P2 | P3
    status: str = Field(default="inbox", index=True)  # inbox | today | done | someday
    due_date: date | None = None
    scheduled_for: date | None = None          # day it lands in "today"
    remind_at: datetime | None = None          # one-off reminder ping (UTC)
    recurrence: str | None = None              # e.g. "daily", "weekly:mon,thu", "monthly:15"
    completed_at: datetime | None = None       # set when status -> done (for weekly stats)
    source: str = Field(default="tg")          # tg | forward | airtable
    airtable_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Setting(SQLModel, table=True):
    """Key/value store for runtime-tunable settings (ping times, tz overrides)."""

    key: str = Field(primary_key=True)
    value: str


class ConvTurn(SQLModel, table=True):
    """Rolling conversation memory so the assistant keeps context across messages."""

    id: int | None = Field(default=None, primary_key=True)
    role: str                      # "user" | "assistant"
    content: str
    created_at: datetime = Field(default_factory=_utcnow, index=True)


class ActionLog(SQLModel, table=True):
    """Reversible action journal powering 'отмени' (undo)."""

    id: int | None = Field(default=None, primary_key=True)
    kind: str                      # "create" | "update" | "delete"
    task_id: int | None = None
    before: str | None = None      # JSON snapshot of the task before the action (null for create)
    summary: str = ""              # human description, e.g. "перенёс «Отчёт» на завтра"
    undone: bool = False
    created_at: datetime = Field(default_factory=_utcnow, index=True)
