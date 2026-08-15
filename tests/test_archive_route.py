"""Message routing: forward / URL / plain text / save mode."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from nudge import handlers
from nudge.archive.pipeline import store_forward_payload
from nudge.archive.route import (
    build_telegram_post_url,
    decide_archive,
    extract_urls,
    is_video_url,
)


def test_forward_always_archive():
    d = decide_archive(text="смотри это", is_forward=True)
    assert d.kind == "archive"
    assert d.reason == "forward"


def test_build_telegram_post_url_public_channel():
    assert (
        build_telegram_post_url(message_id=42, username="mychannel")
        == "https://t.me/mychannel/42"
    )


def test_build_telegram_post_url_private_channel():
    assert (
        build_telegram_post_url(message_id=7, chat_id=-1001234567890)
        == "https://t.me/c/1234567890/7"
    )


def test_forward_telegram_post_url_from_origin():
    chat = SimpleNamespace(username="dee", id=-100111)
    origin = SimpleNamespace(chat=chat, message_id=99)
    msg = SimpleNamespace(forward_origin=origin)
    assert handlers.forward_telegram_post_url(msg) == "https://t.me/dee/99"


def test_forward_telegram_post_url_without_channel_origin():
    msg = SimpleNamespace(forward_origin=SimpleNamespace())
    assert handlers.forward_telegram_post_url(msg) is None


def test_store_forward_prefers_telegram_post_over_inner_urls():
    captured: dict = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return {"id": "bm-tg"}

    with patch("nudge.archive.pipeline.create_bookmark", side_effect=fake_create):
        res = store_forward_payload(
            "смотри https://instagram.com/reel/AbC/ круто",
            urls=["https://instagram.com/reel/AbC/"],
            prefer_url="https://t.me/mychannel/42",
        )
    assert res.ok
    assert captured["url"] == "https://t.me/mychannel/42"
    assert "instagram" in (captured.get("note") or "")


def test_video_url_archive():
    d = decide_archive(text="https://www.tiktok.com/@u/video/1 круто")
    assert d.kind == "archive"
    assert d.is_video is True
    assert d.url and "tiktok" in d.url


def test_plain_link_archive():
    d = decide_archive(text="прочти https://example.com/a")
    assert d.kind == "archive"
    assert d.reason == "link"
    assert d.is_video is False


def test_plain_text_tasks():
    d = decide_archive(text="купить молоко")
    assert d.kind == "tasks"


def test_save_mode():
    d = decide_archive(text="без ссылки просто мысль", save_mode=True)
    assert d.kind == "archive"
    assert d.reason == "save_mode"


def test_extract_urls_strips_punct():
    urls = extract_urls("см. https://example.com/x).")
    assert urls == ["https://example.com/x"]


def test_is_video_url():
    assert is_video_url("https://www.instagram.com/reel/AbC/")
    assert not is_video_url("https://example.com/x")
