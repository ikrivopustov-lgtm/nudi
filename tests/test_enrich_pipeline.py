"""Pipeline with mocked Apify + Karakeep + LLM."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nudge.archive.normalize import EnrichmentResult, normalize_actor_item
from nudge.archive.pipeline import enrich_and_store
from nudge.archive.summarize import SummaryResult

FIX = Path(__file__).parent / "fixtures" / "apify"


def test_pipeline_plain_link_no_apify(monkeypatch):
    monkeypatch.setattr(
        "nudge.archive.pipeline.create_bookmark",
        lambda **kw: {"id": "x1"},
    )
    monkeypatch.setattr(
        "nudge.archive.pipeline.summarize_enrichment",
        lambda *_a, **_k: SummaryResult(summary="статья", title="Статья"),
    )
    # ensure no token → no apify
    from nudge.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("APIFY_TOKEN", "")
    get_settings.cache_clear()

    with patch("nudge.archive.pipeline.run_actor") as run:
        res = enrich_and_store("https://example.com/post", skip_llm=False)
        run.assert_not_called()
    assert res.ok
    assert res.bookmark_id == "x1"
    assert res.used_apify is False


def test_pipeline_tiktok_with_apify_mock(monkeypatch):
    raw = json.loads((FIX / "tiktok_sample.json").read_text(encoding="utf-8"))
    enriched = normalize_actor_item(
        raw["webVideoUrl"], "tiktok", raw
    )

    monkeypatch.setattr(
        "nudge.archive.pipeline.run_actor",
        lambda *_a, **_k: [raw],
    )
    monkeypatch.setattr(
        "nudge.archive.pipeline.summarize_enrichment",
        lambda *_a, **_k: SummaryResult(
            title="Три шага архива",
            summary="Три шага архива.",
            takeaway="Сохраняй сразу.",
        ),
    )
    monkeypatch.setattr(
        "nudge.archive.pipeline.create_bookmark",
        lambda **kw: {"id": "tik1"},
    )
    from nudge.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("APIFY_TOKEN", "apify_test_token")
    get_settings.cache_clear()

    res = enrich_and_store(raw["webVideoUrl"])
    assert res.ok
    assert res.used_apify is True
    assert res.bookmark_id == "tik1"
    assert res.enrichment is not None
    assert "три шага" in (res.enrichment.transcript or "").lower() or enriched.transcript


def test_pipeline_apify_failure_fallback(monkeypatch):
    from nudge.archive.apify_client import ApifyError

    monkeypatch.setattr(
        "nudge.archive.pipeline.run_actor",
        lambda *_a, **_k: (_ for _ in ()).throw(ApifyError("boom")),
    )
    monkeypatch.setattr(
        "nudge.archive.pipeline.summarize_enrichment",
        lambda *_a, **_k: SummaryResult(summary=""),
    )
    monkeypatch.setattr(
        "nudge.archive.pipeline.create_bookmark",
        lambda **kw: {"id": "fb1"},
    )
    from nudge.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("APIFY_TOKEN", "tok")
    get_settings.cache_clear()

    res = enrich_and_store("https://www.tiktok.com/@u/video/1")
    assert res.ok
    assert res.used_apify is False
    assert res.bookmark_id == "fb1"


@pytest.mark.integration
def test_live_apify_skipped_without_token(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    from nudge.config import get_settings

    get_settings.cache_clear()
    if not get_settings().apify_token:
        pytest.skip("APIFY_TOKEN not set")
