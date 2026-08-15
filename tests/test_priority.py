"""choose() — the rule of 5 (no silent inbox top-up)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from nudge import store
from nudge.db import init_db
from nudge.llm import iso_week_of
from nudge.models import Task
from nudge.priority import LIMIT, choose, materialize_today, select_today

TODAY = date(2026, 7, 21)


def mk(title, *, status="inbox", priority="P2", due=None, scheduled_for=None, created_offset=0):
    return Task(
        title=title,
        raw_text=title,
        iso_week="2026-W30",
        status=status,
        priority=priority,
        due_date=due,
        scheduled_for=scheduled_for,
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
    out = choose(tasks, TODAY)
    assert all(t.status != "done" for t in out)
    assert [t.title for t in out] == ["done-today"]


def test_undated_inbox_not_auto_pulled():
    """Capture stays in backlog — no silent top-up into today."""
    tasks = [
        mk("p3-a", priority="P3"),
        mk("p1-a", priority="P1"),
        mk("p2-a", priority="P2"),
        mk("p1-b", priority="P1"),
        mk("p3-b", priority="P3"),
        mk("p2-b", priority="P2"),
    ]
    out = choose(tasks, TODAY)
    assert out == []


def test_overdue_sorted_first():
    tasks = [
        mk("normal-today", status="today", priority="P1"),
        mk("overdue", status="inbox", priority="P3", due=TODAY - timedelta(days=1)),
    ]
    out = choose(tasks, TODAY)
    assert out[0].title == "overdue"  # overdue outranks even a P1 'today'


def test_future_scheduled_not_in_today_after_reschedule():
    """Regression: moved to Tuesday must not reappear in /today."""
    tasks = [
        mk("stay", status="today"),
        mk(
            "moved",
            status="inbox",
            priority="P1",
            scheduled_for=TODAY + timedelta(days=2),
        ),
    ]
    out = choose(tasks, TODAY)
    assert [t.title for t in out] == ["stay"]


def test_scheduled_for_today_included_even_if_inbox():
    tasks = [
        mk("later", status="inbox", scheduled_for=TODAY + timedelta(days=3)),
        mk("due-today", status="inbox", scheduled_for=TODAY, priority="P3"),
    ]
    out = choose(tasks, TODAY)
    assert [t.title for t in out] == ["due-today"]


def test_materialize_promotes_inbox_scheduled_today():
    init_db()
    t = store.create_task(
        title="Всплыла",
        raw_text="Всплыла",
        iso_week=iso_week_of(TODAY),
        status="inbox",
        scheduled_for=TODAY,
    )
    chosen = select_today(TODAY, materialize=True)
    assert any(x.id == t.id for x in chosen)
    assert store.get_task(t.id).status == "today"
    assert t.id not in {x.id for x in store.list_by_status("inbox")}


def test_materialize_promotes_overdue():
    init_db()
    t = store.create_task(
        title="Просрочка",
        raw_text="Просрочка",
        iso_week=iso_week_of(TODAY),
        status="inbox",
        due_date=TODAY - timedelta(days=1),
    )
    n = materialize_today(choose(store.list_active(), TODAY))
    assert n == 1
    assert store.get_task(t.id).status == "today"
