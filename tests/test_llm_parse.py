"""parse_text: validation + fallback. LLM transport is mocked."""

from __future__ import annotations

import json
from datetime import date

import pytest

from nudge import llm

TODAY = date(2026, 7, 21)  # ISO week 2026-W30


def _mock_response(payload: dict | str):
    async def _call(_messages):
        return payload if isinstance(payload, str) else json.dumps(payload)

    return _call


async def test_valid_parse(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_call_openrouter",
        _mock_response(
            {"title": "Позвонить в банк", "project": "Финансы", "priority": "P1", "due_date": "2026-07-25"}
        ),
    )
    out = await llm.parse_text("надо позвонить в банк до пятницы", today=TODAY)
    assert out["title"] == "Позвонить в банк"
    assert out["project"] == "Финансы"
    assert out["priority"] == "P1"
    assert out["due_date"] == date(2026, 7, 25)
    assert out["iso_week"] == "2026-W30"


async def test_bad_priority_is_coerced(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_call_openrouter",
        _mock_response({"title": "x", "project": None, "priority": "URGENT", "due_date": None}),
    )
    out = await llm.parse_text("x", today=TODAY)
    assert out["priority"] == "P2"
    assert out["project"] is None
    assert out["iso_week"] == "2026-W30"


async def test_invalid_due_date_becomes_null(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_call_openrouter",
        _mock_response({"title": "x", "project": None, "priority": "P2", "due_date": "not-a-date"}),
    )
    out = await llm.parse_text("x", today=TODAY)
    assert out["due_date"] is None


async def test_malformed_json_falls_back(monkeypatch):
    monkeypatch.setattr(llm, "_call_openrouter", _mock_response("this is not json{"))
    out = await llm.parse_text("купить молоко", today=TODAY)
    assert out["priority"] == "P2"
    assert out["project"] is None
    assert out["title"] == "купить молоко"


async def test_transport_error_falls_back(monkeypatch):
    async def _boom(_messages):
        raise RuntimeError("network down")

    monkeypatch.setattr(llm, "_call_openrouter", _boom)
    out = await llm.parse_text("починить кран", today=TODAY)
    assert out["title"] == "починить кран"
    assert out["priority"] == "P2"


def test_iso_week_helper():
    assert llm.iso_week_of(date(2026, 7, 21)) == "2026-W30"
    assert llm.iso_week_of(date(2026, 1, 1)) == "2026-W01"
