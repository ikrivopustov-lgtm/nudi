"""Done history — calendar weeks, permanent storage."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from nudge import store
from nudge.db import init_db
from nudge.done_history import (
    done_week_keyboard,
    format_week_range,
    render_done_week,
    week_monday,
)
from nudge.llm import iso_week_of

TODAY = date(2026, 8, 4)  # Tuesday
TZ = ZoneInfo("Europe/Moscow")


def _complete(title: str, *, completed_local: datetime) -> int:
    init_db()
    t = store.create_task(
        title=title,
        raw_text=title,
        iso_week=iso_week_of(TODAY),
        status="today",
    )
    # Store naive UTC (same as complete_task).
    completed_utc = completed_local.astimezone(timezone.utc).replace(tzinfo=None)
    store.update_task(t.id, status="done", completed_at=completed_utc)
    return t.id


def test_week_monday():
    assert week_monday(date(2026, 8, 4)) == date(2026, 8, 3)  # Mon
    assert week_monday(date(2026, 8, 3)) == date(2026, 8, 3)


def test_format_week_range():
    assert "пн 03.08" in format_week_range(date(2026, 8, 3))
    assert "вс 09.08" in format_week_range(date(2026, 8, 3))


def test_render_done_week_lists_task_in_week():
    # Monday 03.08 12:00 MSK
    _complete(
        "Закрыл отчёт",
        completed_local=datetime(2026, 8, 3, 12, 0, tzinfo=TZ),
    )
    text = render_done_week(date(2026, 8, 3), today=TODAY, tz=TZ)
    assert "Закрыл отчёт" in text
    assert "эта неделя" in text
    assert "хранится всегда" in text


def test_render_done_week_excludes_other_week():
    _complete(
        "Старая",
        completed_local=datetime(2026, 7, 20, 12, 0, tzinfo=TZ),
    )
    text = render_done_week(date(2026, 8, 3), today=TODAY, tz=TZ)
    assert "Старая" not in text
    assert "нет" in text.lower() or "Закрытых" in text


def test_keyboard_hides_next_on_current_week():
    kb = done_week_keyboard(date(2026, 8, 3), today=TODAY)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any("пред" in t for t in labels)
    assert not any("след" in t for t in labels)


def test_keyboard_shows_next_on_past_week():
    kb = done_week_keyboard(date(2026, 7, 27), today=TODAY)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any("пред" in t for t in labels)
    assert any("след" in t for t in labels)


def test_done_tasks_never_auto_deleted():
    """Closing keeps the row; status=done is the archive (no purge)."""
    tid = _complete(
        "Навсегда",
        completed_local=datetime(2026, 8, 4, 10, 0, tzinfo=TZ),
    )
    t = store.get_task(tid)
    assert t is not None
    assert t.status == "done"
    assert t.completed_at is not None
    # Still readable weeks later via list API
    since = datetime(2026, 1, 1)
    found = store.list_completed_between(since)
    assert any(x.id == tid for x in found)
