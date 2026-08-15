"""Fast free-form complete / history / inbox — no LLM."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from nudge import store
from nudge.assistant import _Executor
from nudge.db import init_db
from nudge.fastpath import (
    clean_quote_hint,
    extract_create_title,
    extract_reschedule,
    parse_quote_command,
    resolve_relative_date,
    try_fast_complete,
    try_fast_create,
    try_fast_history,
    try_fast_inbox,
    try_fast_path,
    try_fast_reschedule,
    try_quote_action,
)
from nudge.llm import iso_week_of

TODAY = date(2026, 7, 26)
TZ = ZoneInfo("Europe/Moscow")


def _make(title: str, *, status: str = "today") -> int:
    init_db()
    t = store.create_task(
        title=title,
        raw_text=title,
        iso_week=iso_week_of(TODAY),
        status=status,
        scheduled_for=TODAY if status == "today" else None,
    )
    return t.id


def test_fast_complete_сделал_prefix():
    tid = _make("Оплатить налоги")
    reply = try_fast_complete("сделал налоги", today=TODAY, tz=TZ)
    assert reply and "Закрыл" in reply
    assert store.get_task(tid).status == "done"


def test_fast_complete_check_suffix():
    tid = _make("Созвон с Павлом")
    reply = try_fast_complete("созвон с павлом ✓", today=TODAY, tz=TZ)
    assert reply and "Закрыл" in reply
    assert store.get_task(tid).status == "done"


def test_fast_complete_dash_сделано():
    tid = _make("Отчёт")
    reply = try_fast_complete("Отчёт — сделано", today=TODAY, tz=TZ)
    assert reply and "Закрыл" in reply
    assert store.get_task(tid).status == "done"


def test_fast_complete_bare_готово_closes_last():
    _make("Старая", status="inbox")
    tid = _make("Свежая")
    reply = try_fast_complete("готово", today=TODAY, tz=TZ)
    assert reply and "Закрыл" in reply
    assert store.get_task(tid).status == "done"


def test_fast_complete_identical_titles_picks_newest():
    _make("Дубль")
    tid2 = _make("Дубль")
    reply = try_fast_complete("сделал дубль", today=TODAY, tz=TZ)
    assert reply and "Закрыл" in reply
    assert store.get_task(tid2).status == "done"


def test_fast_history():
    tid = _make("Старая")
    _Executor(TODAY, TZ, None).run("complete_task", {"task_id": tid})
    # Pin into the fixture calendar week (complete_task uses wall-clock now).
    store.update_task(
        tid,
        completed_at=datetime(2026, 7, 26, 12, 0, 0),  # naive UTC inside TODAY week
    )
    reply = try_fast_history("что сделал за неделю?", today=TODAY, tz=TZ)
    assert reply and "Старая" in reply


def test_fast_path_prefers_complete_over_history_words():
    tid = _make("Налоги")
    reply = try_fast_path("сделал налоги", today=TODAY, tz=TZ)
    assert reply and "Закрыл" in reply
    assert store.get_task(tid).status == "done"


def test_fast_inbox_lists_tasks():
    _make("Лежит", status="inbox")
    reply = try_fast_inbox("инбокс")
    assert reply and "Лежит" in reply and "/backlog" in reply
    assert "Без даты" in reply or "без даты" in reply


def test_fast_inbox_empty():
    reply = try_fast_inbox("бэклог")
    assert reply and "пуст" in reply.lower()


def test_fast_path_inbox_word():
    _make("A", status="inbox")
    reply = try_fast_path("разбери инбокс", today=TODAY, tz=TZ)
    assert reply and ("Бэклог" in reply or "Без даты" in reply) and "A" in reply


def test_fast_create_postav_prefix():
    # Existing similar word must NOT block create.
    _make("Проверить дата-ленс и подключить б2б агента", status="inbox")
    reply = try_fast_create("поставь ТЗ на фронт и бэк агента", today=TODAY, tz=TZ)
    assert reply and "бэклог" in reply.lower() and "ТЗ на фронт" in reply
    titles = [t.title for t in store.list_active()]
    assert "ТЗ на фронт и бэк агента" in titles
    created = next(t for t in store.list_active() if t.title == "ТЗ на фронт и бэк агента")
    assert created.status == "inbox"


def test_fast_create_bare_title():
    reply = try_fast_create("ТЗ на фронт и бэк агента", today=TODAY, tz=TZ)
    assert reply and "бэклог" in reply.lower()
    created = next(t for t in store.list_active() if t.title == "ТЗ на фронт и бэк агента")
    assert created.status == "inbox"

def test_extract_create_skips_reschedule_and_chitchat():
    assert extract_create_title("поставь на пятницу") is None
    assert extract_create_title("налоги давай на след неделю") is None
    assert extract_create_title("привет") is None
    assert extract_create_title("сделал налоги") is None
    assert extract_create_title("поставь задачу: купить молоко") == "купить молоко"


def test_resolve_relative_date_weekday():
    # TODAY = Sunday 2026-07-26 → вторник = 2026-07-28
    assert resolve_relative_date("вторник", today=TODAY) == date(2026, 7, 28)
    assert resolve_relative_date("завтра", today=TODAY) == date(2026, 7, 27)
    assert resolve_relative_date("след неделю", today=TODAY) == date(2026, 7, 27)  # Mon


def test_extract_reschedule_greenintern():
    parsed = extract_reschedule(
        "Перенести гринтерн и офферсы на вторник", today=TODAY
    )
    assert parsed is not None
    hint, target = parsed
    assert "гринтерн" in hint.lower()
    assert "офферс" in hint.lower()
    assert target == date(2026, 7, 28)


def test_fast_reschedule_matches_title_with_same_verb():
    tid = _make("Перенести гринтерн и офферсы", status="today")
    # Distract with a loosely related «агента» task — must NOT win.
    _make("Проверить дата-ленс и подключить б2б агента", status="inbox")
    reply = try_fast_reschedule(
        "Перенести гринтерн и офферсы на вторник", today=TODAY, tz=TZ
    )
    assert reply and "Перенёс" in reply and "гринтерн" in reply.lower()
    t = store.get_task(tid)
    assert t.scheduled_for == date(2026, 7, 28)
    assert t.status == "inbox"  # moved off today


def test_fast_reschedule_davay_na():
    tid = _make("Оплатить налоги", status="today")
    reply = try_fast_reschedule("налоги давай на след неделю", today=TODAY, tz=TZ)
    assert reply and "Перенёс" in reply
    assert store.get_task(tid).scheduled_for == date(2026, 7, 27)


def test_fast_path_reschedule_before_create():
    tid = _make("Перенести гринтерн и офферсы")
    reply = try_fast_path(
        "Перенести гринтерн и офферсы на вторник", today=TODAY, tz=TZ
    )
    assert reply and "Перенёс" in reply
    assert store.get_task(tid).scheduled_for == date(2026, 7, 28)
    # Must not have created a duplicate
    titles = [t.title for t in store.list_active()]
    assert titles.count("Перенести гринтерн и офферсы") == 1


def test_parse_quote_command_bare_only():
    assert parse_quote_command("сделано") == "complete"
    assert parse_quote_command("готово") == "complete"
    assert parse_quote_command("✓") == "complete"
    assert parse_quote_command("в бэклог") == "backlog"
    assert parse_quote_command("отложи") == "backlog"
    assert parse_quote_command("убери из сегодня") == "backlog"
    # With a title in the body — not a quote-command (normal fastpath handles it).
    assert parse_quote_command("сделал налоги") is None
    assert parse_quote_command("налоги в бэклог") is None
    assert parse_quote_command("https://example.com") is None


def test_clean_quote_hint_strips_digest_chrome():
    assert clean_quote_hint("1. 🟠 подключить дата ленс к б") == "подключить дата ленс к б"
    assert clean_quote_hint("🟠 налоги") == "налоги"
    assert clean_quote_hint("2) купить молоко…") == "купить молоко"


def test_quote_complete_truncated_title():
    tid = _make("подключить дата ленс к б2б агенту")
    reply = try_quote_action(
        "сделано",
        "1. 🟠 подключить дата ленс к б",
        today=TODAY,
        tz=TZ,
    )
    assert reply and "Закрыл" in reply
    assert store.get_task(tid).status == "done"


def test_quote_backlog_parks_from_today():
    tid = _make("ТЗ на фронт и бэк агента", status="today")
    reply = try_quote_action(
        "в бэклог",
        "ТЗ на фронт и бэк агента",
        today=TODAY,
        tz=TZ,
    )
    assert reply and "бэклог" in reply.lower()
    t = store.get_task(tid)
    assert t.status == "inbox"
    assert t.scheduled_for is None


def test_quote_non_command_falls_through():
    _make("налоги")
    assert try_quote_action("привет", "налоги", today=TODAY, tz=TZ) is None
    assert try_quote_action("сделал налоги", "налоги", today=TODAY, tz=TZ) is None


def test_quote_not_found():
    reply = try_quote_action("сделано", "несуществующая задача xyz", today=TODAY, tz=TZ)
    assert reply and "Не нашёл" in reply
