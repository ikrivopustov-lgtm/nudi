"""End-to-end: URL → optional Apify → summary → Karakeep."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..config import get_settings
from .apify_client import ApifyError, run_actor
from .karakeep import KarakeepError, create_bookmark
from .normalize import EnrichmentResult, normalize_dataset
from .route import is_telegram_post_url
from .router import actor_for_url, classify_platform
from .summarize import SummaryResult, summarize_enrichment

log = logging.getLogger(__name__)


@dataclass
class StoreResult:
    ok: bool
    message: str
    bookmark_id: str | None = None
    title: str = ""
    enrichment: EnrichmentResult | None = None
    summary: SummaryResult | None = None
    used_apify: bool = False
    error: str | None = None


def enrich_and_store(
    url: str | None = None,
    *,
    text_note: str | None = None,
    title: str = "",
    context_note: str | None = None,
    skip_apify: bool = False,
    skip_llm: bool = False,
) -> StoreResult:
    """Store a link (with optional enrich) or a plain text note into Karakeep.

    Never raises — returns StoreResult with ok=False on failure.
    """
    settings = get_settings()

    # Plain text note (forward without URL, Save mode note, access card)
    if text_note and not url:
        note_title = title or "Заметка"
        try:
            data = create_bookmark(text=text_note, title=note_title)
            return StoreResult(
                ok=True,
                message=f"сохранил заметку: {note_title}",
                bookmark_id=data.get("id"),
                title=note_title,
            )
        except KarakeepError as e:
            return StoreResult(ok=False, message="не смог сохранить в Karakeep", error=str(e))

    if not url:
        return StoreResult(ok=False, message="нет ссылки и нет текста", error="empty")

    platform = classify_platform(url)
    enrichment = EnrichmentResult(url=url, title=title or url, platform=platform)
    used_apify = False

    job = None if skip_apify else actor_for_url(url)
    if job and settings.apify_token:
        try:
            items = run_actor(job.actor_id, job.run_input, token=settings.apify_token)
            enrichment = normalize_dataset(url, job.platform, items)
            used_apify = True
        except ApifyError as e:
            log.warning("apify failed, fallback to bare link: %s", e)
            enrichment = EnrichmentResult(
                url=url,
                title=title or url,
                platform=platform,
                caption="",
                transcript="",
            )
        except Exception as e:
            log.exception("apify unexpected")
            enrichment = EnrichmentResult(url=url, title=title or url, platform=platform)
            # continue with bare link
            _ = e
    elif job and not settings.apify_token:
        log.info("APIFY_TOKEN empty — storing bare link")

    summary = SummaryResult()
    if not skip_llm and (enrichment.transcript or enrichment.caption or enrichment.title):
        summary = summarize_enrichment(enrichment)

    # Prefer Russian fields in Karakeep; keep a short original only if useful.
    note_parts: list[str] = []
    if context_note and context_note.strip():
        note_parts.append(context_note.strip()[:2000])
    if summary.summary:
        note_parts.append(summary.summary.strip())
    if summary.takeaway:
        note_parts.append(f"Вывод: {summary.takeaway.strip()}")
    if enrichment.author:
        note_parts.append(f"Автор: {enrichment.author}")
    # Original language dump only when we have nothing better (and keep it short).
    if not summary.summary and enrichment.caption:
        note_parts.append(enrichment.caption.strip()[:800])
    note = "\n\n".join(note_parts).strip()

    # Do not invent Karakeep tags — user organizes in UI if needed.
    tags: list[str] = []

    final_title = (
        summary.title
        or title
        or enrichment.title
        or (summary.summary[:60] if summary.summary else url)
    )

    try:
        data = create_bookmark(
            url=enrichment.url or url,
            title=final_title[:200],
            note=note,
            summary=summary.summary,
            tags=tags,
        )
    except KarakeepError as e:
        return StoreResult(
            ok=False,
            message="не смог сохранить в Karakeep",
            enrichment=enrichment,
            summary=summary,
            used_apify=used_apify,
            error=str(e),
        )

    # Short Telegram ACK — tags filled in by handler after AI tagging.
    title_show = final_title.strip()[:80]
    msg = f"✓ в архиве: «{title_show}»"
    return StoreResult(
        ok=True,
        message=msg,
        bookmark_id=data.get("id"),
        title=final_title.strip(),
        enrichment=enrichment,
        summary=summary,
        used_apify=used_apify,
    )


def store_forward_payload(
    text: str,
    *,
    urls: list[str],
    prefer_url: str | None = None,
) -> StoreResult:
    """Forward / Save: prefer_url (TG post) wins over URLs found in the body."""
    primary = prefer_url or (urls[0] if urls else None)
    if primary:
        body = (text or "").strip()
        if prefer_url or is_telegram_post_url(primary):
            title = "Пост в Telegram"
            if body and body not in {"Пересланное сообщение", primary}:
                title = body.split("\n", 1)[0].strip()[:80] or title
            return enrich_and_store(
                primary,
                title=title,
                context_note=body if body and body != primary else None,
                skip_apify=True,
                skip_llm=True,
            )
        return enrich_and_store(
            primary,
            title=text[:80] if text and text != primary else "",
        )
    body = (text or "").strip()
    if not body:
        return StoreResult(ok=False, message="пустое сообщение", error="empty")
    return enrich_and_store(text_note=body, title=body.split("\n", 1)[0][:80])
