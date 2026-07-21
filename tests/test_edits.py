"""parse_edit validation + target resolution."""

from __future__ import annotations

import json
from datetime import date

from nudge import handlers, llm
from nudge.models import Task

TODAY = date(2026, 7, 21)


def _mock(payload):
    async def _call(_messages):
        return payload if isinstance(payload, str) else json.dumps(payload)

    return _call


async def test_done_intent(monkeypatch):
    monkeypatch.setattr(llm, "_call_openrouter", _mock({"action": "done", "target_hint": "отчёт", "value": None}))
    out = await llm.parse_edit("сделал отчёт", today=TODAY)
    assert out["action"] == "done"
    assert out["target_hint"] == "отчёт"


async def test_reschedule_intent(monkeypatch):
    monkeypatch.setattr(llm, "_call_openrouter", _mock({"action": "reschedule", "target_hint": "звонок", "value": "2026-07-22"}))
    out = await llm.parse_edit("сдвинь звонок на завтра", today=TODAY)
    assert out["action"] == "reschedule"
    assert out["value"] == date(2026, 7, 22)


async def test_priority_intent(monkeypatch):
    monkeypatch.setattr(llm, "_call_openrouter", _mock({"action": "priority", "target_hint": "налоги", "value": "P1"}))
    out = await llm.parse_edit("подними приоритет по налогам", today=TODAY)
    assert out["action"] == "priority"
    assert out["value"] == "P1"


async def test_new_task_is_not_an_edit(monkeypatch):
    monkeypatch.setattr(llm, "_call_openrouter", _mock({"action": None, "target_hint": None, "value": None}))
    out = await llm.parse_edit("купить молоко", today=TODAY)
    assert out["action"] is None


async def test_reschedule_without_date_is_not_actionable(monkeypatch):
    monkeypatch.setattr(llm, "_call_openrouter", _mock({"action": "reschedule", "target_hint": "x", "value": "soon"}))
    out = await llm.parse_edit("перенеси x", today=TODAY)
    assert out["action"] is None


async def test_bad_priority_value_nulls_out(monkeypatch):
    monkeypatch.setattr(llm, "_call_openrouter", _mock({"action": "priority", "target_hint": "x", "value": "high"}))
    out = await llm.parse_edit("x", today=TODAY)
    assert out["action"] == "priority"
    assert out["value"] is None


def _mk(title, project=None, tid=1, raw=None):
    t = Task(title=title, raw_text=raw or title, iso_week="2026-W30", project=project)
    t.id = tid
    return t


def test_resolve_target_survives_russian_inflection(monkeypatch):
    """'оплатил' must match 'Оплатить', 'звонок' must match 'Позвонить'."""
    tasks = [
        _mk("Оплатить налоги", project="Налоги", tid=1, raw="надо срочно оплатить налоги до 25 июля"),
        _mk("Позвонить в банк по ипотеке", project="Ипотека", tid=2, raw="позвонить в банк по ипотеке завтра"),
    ]
    monkeypatch.setattr(handlers.store, "list_active", lambda: tasks)
    assert handlers.resolve_target("оплатил налоги").id == 1
    assert handlers.resolve_target("звонок в банк").id == 2


def test_resolve_target_matches(monkeypatch):
    tasks = [_mk("Позвонить в банк", tid=1), _mk("Купить молоко", tid=2)]
    monkeypatch.setattr(handlers.store, "list_active", lambda: tasks)
    hit = handlers.resolve_target("позвонить банк")
    assert hit is not None and hit.id == 1


def test_resolve_target_no_match(monkeypatch):
    tasks = [_mk("Купить молоко", tid=2)]
    monkeypatch.setattr(handlers.store, "list_active", lambda: tasks)
    assert handlers.resolve_target("сделать презентацию") is None
    assert handlers.resolve_target(None) is None
