"""Airtable field mappers (pure, no network)."""

from __future__ import annotations

from datetime import date

from nudge import airtable_sync as at
from nudge.models import Task

TODAY = date(2026, 7, 21)


def test_task_to_fields():
    t = Task(
        title="Позвонить в банк",
        raw_text="x",
        iso_week="2026-W30",
        project="Финансы",
        priority="P1",
        status="today",
        due_date=date(2026, 7, 25),
    )
    f = at.task_to_fields(t, owner="Ilya")
    assert f[at.F_TITLE] == "Позвонить в банк"
    assert f[at.F_OWNER] == "Ilya"
    assert f[at.F_PROJECT] == "Финансы"
    assert f[at.F_WEEK] == "2026-W30"
    assert f[at.F_PRIORITY] == "P1"
    assert f[at.F_STATUS] == "today"
    assert f[at.F_DUE] == "2026-07-25"


def test_task_to_fields_null_due_and_project():
    t = Task(title="x", raw_text="x", iso_week="2026-W30")
    f = at.task_to_fields(t, owner="Ilya")
    assert f[at.F_DUE] is None
    assert f[at.F_PROJECT] == ""


def test_record_to_task_kwargs_full():
    rec = {
        "id": "rec123",
        "fields": {
            at.F_TITLE: "Сделать презентацию",
            at.F_PROJECT: "Работа",
            at.F_PRIORITY: "P1",
            at.F_STATUS: "today",
            at.F_DUE: "2026-07-30",
        },
    }
    kw = at.record_to_task_kwargs(rec, TODAY)
    assert kw["title"] == "Сделать презентацию"
    assert kw["project"] == "Работа"
    assert kw["priority"] == "P1"
    assert kw["status"] == "today"
    assert kw["due_date"] == date(2026, 7, 30)
    assert kw["iso_week"] == "2026-W31"
    assert kw["source"] == "airtable"
    assert kw["airtable_id"] == "rec123"


def test_record_to_task_kwargs_defaults_and_whitelist():
    rec = {"id": "rec9", "fields": {"Name": "из primary поля", at.F_PRIORITY: "SUPER", at.F_STATUS: "weird"}}
    kw = at.record_to_task_kwargs(rec, TODAY)
    assert kw["title"] == "из primary поля"   # falls back to Name
    assert kw["priority"] == "P2"             # bad priority -> default
    assert kw["status"] == "inbox"            # bad status -> default
    assert kw["due_date"] is None
    assert kw["iso_week"] == "2026-W30"       # from TODAY
