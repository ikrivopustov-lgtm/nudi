"""Assistant tool executors + recurrence, exercised directly against a temp DB.

Each user message maps to a FRESH _Executor (as in production), so whole-turn undo
behaves correctly.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from nudge import store
from nudge.assistant import _Executor, next_occurrence
from nudge.db import init_db

TODAY = date(2026, 7, 21)
TZ = ZoneInfo("Europe/Moscow")


def run(tool: str, args: dict, *, sched=None) -> str:
    """One message -> one executor -> one turn."""
    init_db()
    return _Executor(TODAY, TZ, schedule_reminder=sched).run(tool, args)


def _id(out: str) -> int:
    return int(out.split("id=")[1].split()[0])


def test_create_and_complete_and_undo():
    tid = _id(run("create_task", {"title": "Оплатить налоги", "priority": "P1", "due_date": "2026-07-25"}))
    t = store.get_task(tid)
    assert t.priority == "P1" and t.due_date == date(2026, 7, 25)

    run("complete_task", {"task_id": tid})
    assert store.get_task(tid).status == "done"
    assert store.get_task(tid).completed_at is not None

    run("undo_last", {})  # undoes the completion turn only
    assert store.get_task(tid).status != "done"


def test_create_with_reminder_and_recurrence_single_call():
    armed = []
    out = run(
        "create_task",
        {"title": "Созвон", "recurrence": "weekly:mon", "remind_at": "2026-07-27T11:00"},
        sched=lambda tid, when: armed.append((tid, when)),
    )
    t = store.get_task(_id(out))
    assert t.recurrence == "weekly:mon"
    assert t.remind_at is not None and t.remind_at.hour == 8  # 11:00 MSK -> 08:00 UTC
    assert armed and armed[0][0] == t.id


def test_scheduled_today_becomes_today_status():
    tid = _id(run("create_task", {"title": "Позвонить", "scheduled_for": TODAY.isoformat()}))
    assert store.get_task(tid).status == "today"


def test_update_moves_off_today_and_recomputes_week():
    tid = _id(run("create_task", {"title": "X", "scheduled_for": TODAY.isoformat()}))
    assert store.get_task(tid).status == "today"
    run("update_task", {"task_id": tid, "scheduled_for": "2026-08-03"})
    t = store.get_task(tid)
    assert t.status != "today"
    assert t.iso_week == "2026-W32"


def test_deadline_vs_reschedule_are_separate_fields():
    tid = _id(run("create_task", {"title": "Отчёт"}))
    run("update_task", {"task_id": tid, "due_date": "2026-07-30"})
    run("update_task", {"task_id": tid, "scheduled_for": "2026-07-28"})
    t = store.get_task(tid)
    assert t.due_date == date(2026, 7, 30)
    assert t.scheduled_for == date(2026, 7, 28)


def test_delete_and_undo_restores():
    tid = _id(run("create_task", {"title": "Удалить меня"}))
    run("delete_task", {"task_id": tid})
    assert store.get_task(tid) is None
    run("undo_last", {})
    assert store.get_task(tid) is not None
    assert store.get_task(tid).title == "Удалить меня"


def test_whole_turn_undo_reverts_all_actions():
    """Two edits in ONE turn, then one undo -> both reverted."""
    init_db()
    tid = _id(run("create_task", {"title": "Задача"}))
    ex = _Executor(TODAY, TZ, None)  # single turn with two tool calls
    ex.run("update_task", {"task_id": tid, "priority": "P1"})
    ex.run("update_task", {"task_id": tid, "due_date": "2026-08-01"})
    assert store.get_task(tid).priority == "P1"
    run("undo_last", {})
    t = store.get_task(tid)
    assert t.priority == "P2" and t.due_date is None  # both edits gone


def test_undo_guard_once_per_turn():
    tid = _id(run("create_task", {"title": "A"}))
    run("update_task", {"task_id": tid, "priority": "P1"})
    ex = _Executor(TODAY, TZ, None)
    ex.run("undo_last", {})
    second = ex.run("undo_last", {})  # same turn -> refused
    assert "already undone" in second


def test_set_reminder_stores_utc():
    tid = _id(run("create_task", {"title": "Звонок"}))
    run("set_reminder", {"task_id": tid, "remind_at": "2026-07-21T15:00"})
    t = store.get_task(tid)
    assert t.remind_at.hour == 12  # 15:00 MSK -> 12:00 UTC (stored naive)


def test_recurrence_spawns_next_on_complete():
    tid = _id(run("create_task", {"title": "Созвон2", "scheduled_for": "2026-07-27"}))
    run("set_recurrence", {"task_id": tid, "rule": "weekly:mon"})
    before = len(store.list_active())
    run("complete_task", {"task_id": tid})
    after = store.list_active()
    assert len(after) == before  # one closed, one spawned
    assert any(t.recurrence == "weekly:mon" and t.status != "done" for t in after)


def test_next_occurrence_rules():
    assert next_occurrence("daily", date(2026, 7, 21)) == date(2026, 7, 22)
    assert next_occurrence("weekly:mon", date(2026, 7, 21)) == date(2026, 7, 27)
    assert next_occurrence("monthly:15", date(2026, 7, 21)) == date(2026, 8, 15)
    assert next_occurrence("none", date(2026, 7, 21)) is None
