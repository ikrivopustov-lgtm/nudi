"""Handlers keyboard wiring — no Telegram network."""

from __future__ import annotations

from types import SimpleNamespace

from nudge import handlers


def test_message_payload_prefers_caption_and_stub_for_empty():
    msg = SimpleNamespace(
        text=None,
        caption="смотри https://example.com/x",
        entities=None,
        caption_entities=None,
    )
    body, urls = handlers.message_payload(msg)
    assert "example.com" in body
    assert urls and "example.com" in urls[0]


def test_message_payload_empty_media():
    msg = SimpleNamespace(
        text=None,
        caption=None,
        entities=None,
        caption_entities=None,
    )
    body, urls = handlers.message_payload(msg)
    assert body == ""
    assert urls == []


def test_is_forwarded_uses_origin():
    assert handlers.is_forwarded(SimpleNamespace(forward_origin=object(), is_automatic_forward=False))
    assert handlers.is_forwarded(SimpleNamespace(forward_origin=None, is_automatic_forward=True))
    assert not handlers.is_forwarded(SimpleNamespace(forward_origin=None, is_automatic_forward=False))


def test_keyboard_has_backlog_done_and_save():
    rows = handlers.MAIN_KEYBOARD.keyboard
    flat = [btn.text for row in rows for btn in row]
    assert handlers.BTN_TODAY in flat
    assert handlers.BTN_BACKLOG in flat
    assert handlers.BTN_DONE in flat
    assert handlers.BTN_SAVE in flat
    assert handlers.BTN_HELP in flat


def test_backlog_button_label_unchanged():
    """Telegram matches exact string — must stay «📋 Бэклог»."""
    assert handlers.BTN_BACKLOG == "📋 Бэклог"


def test_save_button_label():
    assert handlers.BTN_SAVE == "📎 Сохранить"


def test_help_mentions_inbox_archive_and_reminders():
    assert "инбокс" in handlers.HELP_TEXT.lower() or "Инбокс" in handlers.HELP_TEXT
    assert "напомин" in handlers.HELP_TEXT.lower()
    assert "/backlog" in handlers.HELP_TEXT
    assert "Karakeep" in handlers.HELP_TEXT or "архив" in handlers.HELP_TEXT.lower()
    assert "переслан" in handlers.HELP_TEXT.lower()
    assert "тег" in handlers.HELP_TEXT.lower()
    assert "запят" in handlers.HELP_TEXT.lower()
    assert "Цитировать" in handlers.HELP_TEXT
    assert "в бэклог" in handlers.HELP_TEXT.lower() or "бэклог" in handlers.HELP_TEXT.lower()
