"""choose() — the rule of 5."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from nudge.models import Task
from nudge.priority import LIMIT, choose

TODAY = date(2026, 7, 21)


def mk(title, *, status="inbox", priority="P2", due=None, created_offset=0):
    return Task(
        title=title,
        raw_text=title,
        iso_week="2026-W30",
        status=status,
        priority=priority,
        due_date=due,
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc) + timedelta(hours=created_offset),
    )


def test_caps_at_five():
    tasks = [mk(f"t{i}", status="today") for i in range(8)]
    assert len(choose(tasks, TODAY)) == LIMIT


def test_overdue_included_even_from_inbox():
    tasks = [mk("overdue", status="inbox", due=TODAY - timedelta(days=2))]
    out = choose(tasks, TODAY)
    assert [t.title for t in out] == ["overdue"]


def test_done_excluded():
    tasks = [mk("done-today", status="today"), mk("d", status="done")]
    # A done task must never appear, even if it were 'today' earlier.
    out = choose(tasks, TODAY)
    assert all(t.status != "done" for t in out)
    assert [t.title for t in out] == ["done-today"]


def test_someday_not_topped_up():
    tasks = [mk("later", status="someday", priority="P1")]
    assert choose(tasks, TODAY) == []


def test_topup_prefers_higher_priority():
    # 6 inbox tasks, none 'today'/overdue -> top-up must pick the 5 by priority.
    tasks = [
        mk("p3-a", priority="P3"),
        mk("p1-a", priority="P1"),
        mk("p2-a", priority="P2"),
        mk("p1-b", priority="P1"),
        mk("p3-b", priority="P3"),
        mk("p2-b", priority="P2"),
    ]
    out = choose(tasks, TODAY)
    assert len(out) == LIMIT
    titles = {t.title for t in out}
    # both P1 and both P2 must be in; exactly one P3 dropped.
    assert {"p1-a", "p1-b", "p2-a", "p2-b"} <= titles
    assert len([t for t in out if t.priority == "P3"]) == 1


def test_overdue_sorted_first():
    tasks = [
        mk("normal-today", status="today", priority="P1"),
        mk("overdue", status="inbox", priority="P3", due=TODAY - timedelta(days=1)),
    ]
    out = choose(tasks, TODAY)
    assert out[0].title == "overdue"  # overdue outranks even a P1 'today'
