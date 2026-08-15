"""Backlog split: dated queue vs undated inbox."""

from __future__ import annotations

from datetime import date, datetime, timezone

from nudge.digest import format_scheduled, split_inbox
from nudge.models import Task


def mk(title, *, scheduled_for=None):
    return Task(
        title=title,
        raw_text=title,
        iso_week="2026-W30",
        status="inbox",
        scheduled_for=scheduled_for,
        updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def test_format_scheduled_weekday():
    # 2026-07-28 is Tuesday
    assert format_scheduled(date(2026, 7, 28)) == "вт 28.07"


def test_split_inbox_orders_dated_and_undated():
    a = mk("later", scheduled_for=date(2026, 8, 1))
    b = mk("sooner", scheduled_for=date(2026, 7, 28))
    c = mk("no-date")
    dated, undated = split_inbox([a, b, c])
    assert [t.title for t in dated] == ["sooner", "later"]
    assert [t.title for t in undated] == ["no-date"]
