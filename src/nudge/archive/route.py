"""Decide whether a Telegram message goes to Karakeep archive or tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# Hosts that need Apify enrich (short video).
_VIDEO_HOST_RE = re.compile(
    r"(?:^|\.)("
    r"tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com|"
    r"instagram\.com|"
    r"youtube\.com|youtu\.be|"
    r"facebook\.com|fb\.watch"
    r")(?:/|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ArchiveDecision:
    """Routing result before any LLM / Apify call."""

    kind: str  # archive | tasks | ask
    reason: str
    url: str | None = None
    is_video: bool = False


def extract_urls(text: str) -> list[str]:
    return [m.group(0).rstrip(").,;]") for m in _URL_RE.finditer(text or "")]


def build_telegram_post_url(
    *,
    message_id: int,
    username: str | None = None,
    chat_id: int | None = None,
) -> str | None:
    """Public t.me link to a channel/supergroup message, or None if impossible."""
    if message_id <= 0:
        return None
    if username:
        return f"https://t.me/{username.lstrip('@')}/{message_id}"
    if chat_id is None:
        return None
    # Channels/supergroups: -100xxxxxxxxxx → t.me/c/xxxxxxxxxx/msg
    raw = str(chat_id)
    if raw.startswith("-100"):
        return f"https://t.me/c/{raw[4:]}/{message_id}"
    return None


def is_telegram_post_url(url: str) -> bool:
    u = (url or "").lower()
    return "t.me/" in u or "telegram.me/" in u


def is_video_url(url: str) -> bool:
    # strip scheme and path host
    host = re.sub(r"^https?://", "", url, flags=re.IGNORECASE).split("/")[0].lower()
    host = host.split("@")[-1]  # user@host rare
    if host.startswith("www."):
        host = host[4:]
    return bool(_VIDEO_HOST_RE.search(host + "/"))


def decide_archive(
    *,
    text: str,
    is_forward: bool = False,
    save_mode: bool = False,
) -> ArchiveDecision:
    """Hard routing rules from the plan.

    - Save mode / forward → always archive
    - Video URL → archive + enrich
    - Other http(s) → archive (plain link)
    - Plain text → tasks
    """
    urls = extract_urls(text)
    primary = urls[0] if urls else None
    video = bool(primary and is_video_url(primary))

    if save_mode:
        return ArchiveDecision(
            kind="archive",
            reason="save_mode",
            url=primary,
            is_video=video,
        )
    if is_forward:
        return ArchiveDecision(
            kind="archive",
            reason="forward",
            url=primary,
            is_video=video,
        )
    if primary and video:
        return ArchiveDecision(
            kind="archive",
            reason="video_url",
            url=primary,
            is_video=True,
        )
    if primary:
        return ArchiveDecision(
            kind="archive",
            reason="link",
            url=primary,
            is_video=False,
        )
    return ArchiveDecision(kind="tasks", reason="plain_text")
