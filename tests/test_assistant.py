"""Assistant tool executors + recurrence — isolated temp DB via conftest."""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from nudge import store
from nudge.assistant import _Executor, next_occurrence
from nudge.db import init_db
from nudge.priority import select_today

TODAY = date(2026, 7, 21)
TZ = ZoneInfo("Europe/Moscow")


def run(tool: str, args: dict, *, sched=None) -> str:
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

    run("undo_last", {})
    assert store.get_task(tid).status != "done"


def test_create_defaults_to_inbox():
    tid = _id(run("create_task", {"title": "Без даты"}))
    assert store.get_task(tid).status == "inbox"


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


def test_create_with_project_and_priority():
    tid = _id(run("create_task", {
        "title": "Починить женю",
        "project": "ИИ-платформа",
        "priority": "P1",
    }))
    t = store.get_task(tid)
    assert t.project == "ИИ-платформа" and t.priority == "P1"


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


def test_postpone_to_backlog_inbox():
    """«Отложи» without a date → inbox (backlog), not someday."""
    tid = _id(run("create_task", {"title": "Идея", "scheduled_for": TODAY.isoformat()}))
    run("update_task", {"task_id": tid, "status": "inbox"})
    t = store.get_task(tid)
    assert t.status == "inbox"
    assert t.scheduled_for is None


def test_postpone_to_specific_date_keeps_inbox_with_schedule():
    tid = _id(run("create_task", {"title": "Налоги", "scheduled_for": TODAY.isoformat()}))
    run("update_task", {"task_id": tid, "scheduled_for": "2026-07-25", "status": "inbox"})
    t = store.get_task(tid)
    assert t.status == "inbox"
    assert t.scheduled_for == date(2026, 7, 25)


def test_someday_status_maps_to_inbox():
    tid = _id(run("create_task", {"title": "Legacy", "scheduled_for": TODAY.isoformat()}))
    run("update_task", {"task_id": tid, "status": "someday"})
    t = store.get_task(tid)
    assert t.status == "inbox"


def test_reschedule_tomorrow_leaves_today_status():
    """Moving scheduled_for off today clears status=today; undated top-up is gone."""
    tid = _id(run("create_task", {"title": "Отчёт", "scheduled_for": TODAY.isoformat()}))
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    run("update_task", {"task_id": tid, "scheduled_for": tomorrow})
    t = store.get_task(tid)
    assert t.scheduled_for == TODAY + timedelta(days=1)
    assert t.status != "today"
    assert tid not in {x.id for x in select_today(TODAY, materialize=False)}


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
    init_db()
    tid = _id(run("create_task", {"title": "Задача"}))
    ex = _Executor(TODAY, TZ, None)
    ex.run("update_task", {"task_id": tid, "priority": "P1"})
    ex.run("update_task", {"task_id": tid, "due_date": "2026-08-01"})
    assert store.get_task(tid).priority == "P1"
    run("undo_last", {})
    t = store.get_task(tid)
    assert t.priority == "P2" and t.due_date is None


def test_undo_guard_once_per_turn():
    tid = _id(run("create_task", {"title": "A"}))
    run("update_task", {"task_id": tid, "priority": "P1"})
    ex = _Executor(TODAY, TZ, None)
    ex.run("undo_last", {})
    second = ex.run("undo_last", {})
    assert "already undone" in second


def test_set_reminder_stores_utc():
    tid = _id(run("create_task", {"title": "Звонок"}))
    armed = []
    run("set_reminder", {"task_id": tid, "remind_at": "2026-07-21T15:00"}, sched=lambda i, w: armed.append((i, w)))
    t = store.get_task(tid)
    assert t.remind_at.hour == 12  # 15:00 MSK -> 12:00 UTC
    assert armed and armed[0][0] == tid


def test_recurrence_spawns_next_on_complete():
    tid = _id(run("create_task", {"title": "Созвон2", "scheduled_for": "2026-07-27"}))
    run("set_recurrence", {"task_id": tid, "rule": "weekly:mon"})
    before = len(store.list_active())
    run("complete_task", {"task_id": tid})
    after = store.list_active()
    assert len(after) == before
    assert any(t.recurrence == "weekly:mon" and t.status != "done" for t in after)


def test_next_occurrence_rules():
    assert next_occurrence("daily", date(2026, 7, 21)) == date(2026, 7, 22)
    assert next_occurrence("weekly:mon", date(2026, 7, 21)) == date(2026, 7, 27)
    assert next_occurrence("monthly:15", date(2026, 7, 21)) == date(2026, 8, 15)
    assert next_occurrence("none", date(2026, 7, 21)) is None


def test_update_task_status_done_delegates_to_complete():
    tid = _id(run("create_task", {"title": "Налоги", "scheduled_for": TODAY.isoformat()}))
    assert store.get_task(tid).status == "today"
    out = run("update_task", {"task_id": tid, "status": "done"})
    assert out.startswith("completed")
    t = store.get_task(tid)
    assert t.status == "done"
    assert t.completed_at is not None
    assert tid not in {x.id for x in select_today(TODAY)}


def test_list_completed_and_search_include_done():
    unique = "УникальныйОтчётXYZ42"
    tid = _id(run("create_task", {"title": unique}))
    run("complete_task", {"task_id": tid})
    out = run("list_completed", {"days": 7})
    assert unique in out
    found = run("search_tasks", {"query": unique, "include_done": True})
    assert unique in found
    hidden = run("search_tasks", {"query": unique, "include_done": False})
    assert hidden == "no matches"


def test_inbox_not_forced_today_when_full():
    tid = _id(run("create_task", {"title": "Лежит в инбоксе"}))
    assert store.get_task(tid).status == "inbox"
    for i in range(5):
        run("create_task", {"title": f"Занят{i}", "scheduled_for": TODAY.isoformat(), "priority": "P1"})
    assert tid not in {x.id for x in select_today(TODAY)}


def test_undated_inbox_never_in_today():
    """Even with empty today, undated capture stays in backlog."""
    tid = _id(run("create_task", {"title": "Просто захват"}))
    assert store.get_task(tid).status == "inbox"
    assert tid not in {x.id for x in select_today(TODAY)}


def test_overdue_appears_in_today():
    tid = _id(run("create_task", {"title": "Просрочка", "due_date": "2026-07-01"}))
    assert store.get_task(tid).status == "inbox"
    ids = {x.id for x in select_today(TODAY)}
    assert tid in ids
    assert store.get_task(tid).status == "today"  # materialize
    assert tid not in {x.id for x in store.list_by_status("inbox")}
