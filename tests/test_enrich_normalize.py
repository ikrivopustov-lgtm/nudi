"""Normalize Apify fixtures → EnrichmentResult."""

from __future__ import annotations

import json
from pathlib import Path

from nudge.archive.normalize import normalize_actor_item, normalize_dataset

FIX = Path(__file__).parent / "fixtures" / "apify"


def test_normalize_tiktok_fixture():
    data = json.loads((FIX / "tiktok_sample.json").read_text(encoding="utf-8"))
    item = normalize_actor_item(
        "https://www.tiktok.com/@demo/video/7123456789012345678",
        "tiktok",
        data,
    )
    assert "архив" in item.caption.lower() or "закладок" in item.caption.lower()
    assert "три шага" in item.transcript
    assert item.author in ("demo", "Demo User")
    assert "productivity" in item.hashtags
    assert "Описание:" in item.note
    assert "Расшифровка:" in item.note


def test_normalize_instagram_fixture():
    data = json.loads((FIX / "instagram_reel_sample.json").read_text(encoding="utf-8"))
    item = normalize_dataset(
        "https://www.instagram.com/reel/AbCdEfGhIjK/",
        "instagram",
        [data],
    )
    assert item.author == "focus.lab"
    assert "уведомления" in item.transcript
    assert "focus" in item.hashtags


def test_normalize_empty():
    item = normalize_dataset("https://example.com/x", "link", [])
    assert item.url == "https://example.com/x"
    assert item.transcript == ""


def test_normalize_youtube_codepoetry_shape():
    raw = {
        "metadata": {
            "id": "abc",
            "title": "Реальный заказ на вайбкодинг",
            "url": "https://www.youtube.com/watch?v=abc",
            "channel": "Designer",
        },
        "transcript_text": "I know that vibe coding is a hot topic.",
        "transcript_llm": "I know that vibe coding is a hot topic.",
        "transcript_json": [
            {"start": 0, "end": 1, "text": "I know"},
            {"start": 1, "end": 2, "text": "that vibe coding"},
        ],
    }
    item = normalize_actor_item("https://youtu.be/abc", "youtube", raw)
    assert "вайбкодинг" in item.title
    assert "hot topic" in item.transcript
    assert item.author == "Designer"
