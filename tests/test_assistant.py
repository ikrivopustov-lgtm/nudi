"""Assistant tool executors + recurrence, exercised directly against a temp DB."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from nudge import store
from nudge.assistant import _Executor, next_occurrence
from nudge.db import init_db

TODAY = date(2026, 7, 21)
TZ = ZoneInfo("Europe/Moscow")


def _ex():
    init_db()
    return _Executor(TODAY, TZ, schedule_reminder=None)


def test_create_and_complete_and_undo():
    ex = _ex()
    out = ex.run("create_task", {"title": "Оплатить налоги", "priority": "P1", "due_date": "2026-07-25"})
    assert "created" in out
    tid = int(out.split("id=")[1].split()[0])
    t = store.get_task(tid)
    assert t.priority == "P1" and t.due_date == date(2026, 7, 25)

    ex.run("complete_task", {"task_id": tid})
    assert store.get_task(tid).status == "done"
    assert store.get_task(tid).completed_at is not None

    # undo the completion -> back to previous status
    ex.run("undo_last", {})
    assert store.get_task(tid).status != "done"


def test_create_with_reminder_and_recurrence_single_call():
    armed = []
    init_db()
    ex = _Executor(TODAY, TZ, schedule_reminder=lambda tid, when: armed.append((tid, when)))
    out = ex.run("create_task", {
        "title": "Созвон", "recurrence": "weekly:mon", "remind_at": "2026-07-27T11:00",
    })
    tid = int(out.split("id=")[1].split()[0])
    t = store.get_task(tid)
    assert t.recurrence == "weekly:mon"
    assert t.remind_at is not None and t.remind_at.hour == 8  # 11:00 MSK -> 08:00 UTC
    assert armed and armed[0][0] == tid  # reminder armed for THIS task


def test_scheduled_today_becomes_today_status():
    ex = _ex()
    out = ex.run("create_task", {"title": "Позвонить", "scheduled_for": TODAY.isoformat()})
    tid = int(out.split("id=")[1].split()[0])
    assert store.get_task(tid).status == "today"


def test_update_moves_off_today_and_recomputes_week():
    ex = _ex()
    tid = int(ex.run("create_task", {"title": "X", "scheduled_for": TODAY.isoformat()}).split("id=")[1].split()[0])
    assert store.get_task(tid).status == "today"
    ex.run("update_task", {"task_id": tid, "scheduled_for": "2026-08-03"})
    t = store.get_task(tid)
    assert t.status != "today"
    assert t.iso_week == "2026-W32"


def test_deadline_vs_reschedule_are_separate_fields():
    ex = _ex()
    tid = int(ex.run("create_task", {"title": "Отчёт"}).split("id=")[1].split()[0])
    ex.run("update_task", {"task_id": tid, "due_date": "2026-07-30"})
    ex.run("update_task", {"task_id": tid, "scheduled_for": "2026-07-28"})
    t = store.get_task(tid)
    assert t.due_date == date(2026, 7, 30)
    assert t.scheduled_for == date(2026, 7, 28)


def test_delete_and_undo_restores():
    ex = _ex()
    tid = int(ex.run("create_task", {"title": "Удалить меня"}).split("id=")[1].split()[0])
    ex.run("delete_task", {"task_id": tid})
    assert store.get_task(tid) is None
    ex.run("undo_last", {})
    assert store.get_task(tid) is not None
    assert store.get_task(tid).title == "Удалить меня"


def test_set_reminder_stores_utc():
    ex = _ex()
    tid = int(ex.run("create_task", {"title": "Звонок"}).split("id=")[1].split()[0])
    ex.run("set_reminder", {"task_id": tid, "remind_at": "2026-07-21T15:00"})
    t = store.get_task(tid)
    # 15:00 Moscow (UTC+3) stored as 12:00 UTC (SQLite returns it naive)
    assert t.remind_at.hour == 12


def test_recurrence_spawns_next_on_complete():
    ex = _ex()
    tid = int(ex.run("create_task", {"title": "Созвон", "scheduled_for": "2026-07-27"}).split("id=")[1].split()[0])
    ex.run("set_recurrence", {"task_id": tid, "rule": "weekly:mon"})
    before = len(store.list_active())
    ex.run("complete_task", {"task_id": tid})
    after = store.list_active()
    assert len(after) == before  # one closed, one spawned
    assert any(t.recurrence == "weekly:mon" and t.status != "done" for t in after)


def test_next_occurrence_rules():
    assert next_occurrence("daily", date(2026, 7, 21)) == date(2026, 7, 22)
    # 2026-07-21 is a Tuesday; next Monday is 2026-07-27
    assert next_occurrence("weekly:mon", date(2026, 7, 21)) == date(2026, 7, 27)
    assert next_occurrence("monthly:15", date(2026, 7, 21)) == date(2026, 8, 15)
    assert next_occurrence("none", date(2026, 7, 21)) is None
