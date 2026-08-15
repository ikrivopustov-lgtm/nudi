"""Tests for URL → Apify Actor routing."""

from __future__ import annotations

from nudge.archive.router import actor_for_url, classify_platform


def test_classify_tiktok():
    assert classify_platform("https://www.tiktok.com/@u/video/1") == "tiktok"
    assert classify_platform("https://vm.tiktok.com/ZMabc/") == "tiktok"


def test_classify_instagram():
    assert classify_platform("https://www.instagram.com/reel/AbC/") == "instagram"


def test_classify_youtube():
    assert classify_platform("https://www.youtube.com/shorts/xyz") == "youtube"
    assert classify_platform("https://youtu.be/xyz") == "youtube"


def test_classify_plain_link():
    assert classify_platform("https://example.com/article") == "link"


def test_actor_tiktok():
    job = actor_for_url("https://www.tiktok.com/@u/video/1")
    assert job is not None
    assert "tiktok" in job.actor_id
    assert "postURLs" in job.run_input


def test_actor_instagram():
    job = actor_for_url("https://www.instagram.com/reel/AbC/")
    assert job is not None
    assert job.actor_id == "apify/instagram-reel-scraper"
    assert job.run_input.get("includeTranscript") is True


def test_actor_plain_none():
    assert actor_for_url("https://docs.python.org/3/") is None
