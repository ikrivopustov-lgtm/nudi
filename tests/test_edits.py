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


async def test_deadline_intent(monkeypatch):
    monkeypatch.setattr(llm, "_call_openrouter", _mock({"action": "deadline", "target_hint": "отчёт", "value": "2026-07-30"}))
    out = await llm.parse_edit("поставь дедлайн по отчёту на 30 июля", today=TODAY)
    assert out["action"] == "deadline"
    assert out["value"] == date(2026, 7, 30)


async def test_deadline_without_date_is_not_actionable(monkeypatch):
    monkeypatch.setattr(llm, "_call_openrouter", _mock({"action": "deadline", "target_hint": "x", "value": "скоро"}))
    out = await llm.parse_edit("поставь дедлайн", today=TODAY)
    assert out["action"] is None


def test_deictic_detection():
    assert handlers._is_deictic("эту задачу")
    assert handlers._is_deictic("её")
    assert handlers._is_deictic("последнюю")
    assert handlers._is_deictic(None)
    assert not handlers._is_deictic("оплатить налоги")
    assert not handlers._is_deictic("эту презентацию")  # names something real


def test_target_from_reply(monkeypatch):
    task = _mk("Оплатить налоги", tid=7)
    monkeypatch.setattr(handlers.store, "get_task", lambda tid: task if tid == 7 else None)

    class Msg:
        text = "давай на завтра"
        reply_to_message = type("R", (), {"text": "✅ Задача #7: Оплатить налоги", "caption": None})()

    assert handlers.target_from_reply(Msg()).id == 7


def test_target_from_reply_none_without_card(monkeypatch):
    class Msg:
        text = "давай на завтра"
        reply_to_message = type("R", (), {"text": "просто текст", "caption": None})()

    assert handlers.target_from_reply(Msg()) is None

    class NoReply:
        text = "давай на завтра"
        reply_to_message = None

    assert handlers.target_from_reply(NoReply()) is None


def test_resolve_target_no_match(monkeypatch):
    tasks = [_mk("Купить молоко", tid=2)]
    monkeypatch.setattr(handlers.store, "list_active", lambda: tasks)
    assert handlers.resolve_target("сделать презентацию") is None
    assert handlers.resolve_target(None) is None
