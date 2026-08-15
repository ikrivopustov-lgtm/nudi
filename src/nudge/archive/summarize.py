"""LLM summary for enriched archive items (OpenRouter). Russian only, no tag spam."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import get_settings
from .normalize import EnrichmentResult

log = logging.getLogger(__name__)

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_TIMEOUT = httpx.Timeout(45.0)

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


@dataclass
class SummaryResult:
    title: str = ""
    summary: str = ""
    takeaway: str = ""
    # Kept for backward-compatible tests; pipeline no longer writes tags to Karakeep.
    tags: list[str] = field(default_factory=list)


def _parse_summary_json(text: str) -> SummaryResult:
    raw = (text or "").strip()
    if not raw:
        return SummaryResult()
    match = _JSON_BLOCK.search(raw)
    blob = match.group(0) if match else raw
    try:
        data: dict[str, Any] = json.loads(blob)
    except json.JSONDecodeError:
        return SummaryResult(summary=raw[:500])
    return SummaryResult(
        title=str(data.get("title") or "").strip()[:120],
        summary=str(data.get("summary") or "").strip()[:800],
        takeaway=str(data.get("takeaway") or "").strip()[:400],
        tags=[],
    )


def summarize_enrichment(
    item: EnrichmentResult,
    *,
    client: httpx.Client | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> SummaryResult:
    """Call OpenRouter; on failure return empty summary (caller still stores link)."""
    settings = get_settings()
    key = api_key if api_key is not None else settings.openrouter_api_key
    if not key:
        return SummaryResult(summary=(item.caption or item.title)[:400])

    substance = f"{item.caption} {item.transcript}".strip()
    if len(substance) < 40 and len((item.title or "").strip()) < 20:
        return SummaryResult(
            title="",
            summary=(
                item.caption
                or item.title
                or "Мало текста у источника — сохранена ссылка."
            )[:400],
        )

    model_name = model or settings.openrouter_model
    user_blob = {
        "url": item.url,
        "platform": item.platform,
        "source_title": item.title,
        "author": item.author,
        "caption": item.caption[:2000],
        "transcript": item.transcript[:6000],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Ты помощник личного архива. Верни ТОЛЬКО JSON без markdown:\n"
                '{"title":"короткий заголовок","summary":"2-3 предложения",'
                '"takeaway":"один полезный вывод"}\n'
                "Правила:\n"
                "— title, summary и takeaway СТРОГО на русском языке "
                "(переведи смысл, если источник на другом языке);\n"
                "— title: до 80 символов, без хештегов и без водяных знаков;\n"
                "— не придумывай факты, которых нет в caption/transcript/title;\n"
                "— никаких tags, хештегов и списков ключевых слов."
            ),
        },
        {"role": "user", "content": json.dumps(user_blob, ensure_ascii=False)},
    ]
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.2,
    }

    own = client is None
    http = client or httpx.Client(timeout=_TIMEOUT)
    try:
        resp = http.post(
            _ENDPOINT,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if resp.status_code >= 400:
            log.warning("summarize http %s: %s", resp.status_code, resp.text[:200])
            return SummaryResult(summary=(item.caption or item.title)[:400])
        body = resp.json()
        content = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return _parse_summary_json(content)
    except Exception:
        log.exception("summarize failed")
        return SummaryResult(summary=(item.caption or item.title)[:400])
    finally:
        if own:
            http.close()


# Exported for tests
parse_summary_json = _parse_summary_json
