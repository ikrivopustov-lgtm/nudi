"""Normalize heterogeneous Apify Actor JSON into EnrichmentResult fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EnrichmentResult:
    url: str
    title: str = ""
    caption: str = ""
    transcript: str = ""
    author: str = ""
    platform: str = ""
    hashtags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def note(self) -> str:
        parts: list[str] = []
        if self.caption:
            parts.append(f"Описание:\n{self.caption.strip()}")
        if self.transcript:
            parts.append(f"Расшифровка:\n{self.transcript.strip()}")
        if self.author:
            parts.append(f"Автор: {self.author}")
        return "\n\n".join(parts).strip()


def _first_str(*values: Any) -> str:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _as_list(item: dict[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if item is None:
        return []
    if isinstance(item, list):
        return [x for x in item if isinstance(x, dict)]
    if isinstance(item, dict):
        return [item]
    return []


def _meta_dict(data: dict[str, Any]) -> dict[str, Any]:
    meta = data.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _fetch_url_text(link: str) -> str:
    """Best-effort fetch of a remote transcript/subtitle body."""
    if not link or not link.startswith("http"):
        return ""
    try:
        import httpx

        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(link)
            if resp.status_code >= 400:
                return ""
            text = resp.text.strip()
            # JSON transcript arrays from some hosts
            if text.startswith("[") or text.startswith("{"):
                import json

                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    return text[:20000]
                if isinstance(parsed, list):
                    bits = []
                    for row in parsed:
                        if isinstance(row, dict) and row.get("text"):
                            bits.append(str(row["text"]))
                        elif isinstance(row, str):
                            bits.append(row)
                    return " ".join(bits).strip()
                if isinstance(parsed, dict):
                    return _first_str(
                        parsed.get("text"),
                        parsed.get("transcript"),
                        parsed.get("transcription"),
                    )
            return text[:20000]
    except Exception:
        return ""


def normalize_actor_item(
    url: str,
    platform: str,
    item: dict[str, Any] | None,
) -> EnrichmentResult:
    """Map one dataset item (or empty) to EnrichmentResult. Never raises."""
    data = item or {}
    meta = _meta_dict(data)

    caption = _first_str(
        data.get("text"),
        data.get("caption"),
        data.get("description"),
        data.get("title"),
        meta.get("title"),
        meta.get("description"),
    )
    transcript = _first_str(
        data.get("transcript"),
        data.get("transcriptText"),
        data.get("transcript_text"),
        data.get("transcript_llm"),
        data.get("transcription"),
        data.get("fullTranscript"),
    )
    # Nested subtitle / segments
    if not transcript and isinstance(data.get("videoMeta"), dict):
        vm = data["videoMeta"]
        transcript = _first_str(vm.get("transcript"), vm.get("subtitleText"))
        if not transcript:
            transcript = _fetch_url_text(
                _first_str(vm.get("transcriptionLink"), vm.get("subtitleUrl"))
            )
        if not transcript and isinstance(vm.get("subtitleLinks"), list):
            for sub in vm["subtitleLinks"]:
                if isinstance(sub, dict):
                    transcript = _fetch_url_text(
                        _first_str(sub.get("downloadLink"), sub.get("url"), sub.get("link"))
                    )
                elif isinstance(sub, str):
                    transcript = _fetch_url_text(sub)
                if transcript:
                    break
    if not transcript and isinstance(data.get("segments"), list):
        bits = [
            s.get("text", "")
            for s in data["segments"]
            if isinstance(s, dict) and s.get("text")
        ]
        transcript = " ".join(bits).strip()
    if not transcript and isinstance(data.get("transcript_json"), list):
        bits = [
            s.get("text", "")
            for s in data["transcript_json"]
            if isinstance(s, dict) and s.get("text")
        ]
        transcript = " ".join(bits).strip()

    author = _first_str(
        data.get("author"),
        data.get("ownerUsername"),
        data.get("channel"),
        meta.get("channel"),
        meta.get("author"),
        (data.get("authorMeta") or {}).get("name")
        if isinstance(data.get("authorMeta"), dict)
        else "",
        (data.get("authorMeta") or {}).get("nickName")
        if isinstance(data.get("authorMeta"), dict)
        else "",
    )

    hashtags: list[str] = []
    raw_tags = data.get("hashtags") or data.get("tags") or []
    if isinstance(raw_tags, list):
        for t in raw_tags:
            if isinstance(t, str):
                hashtags.append(t.lstrip("#"))
            elif isinstance(t, dict):
                name = t.get("name") or t.get("id")
                if name:
                    hashtags.append(str(name).lstrip("#"))

    title = _first_str(
        data.get("title"),
        meta.get("title"),
        caption[:80] if caption else "",
        f"{author} — {platform}" if author else platform or url,
    )

    resolved_url = _first_str(
        data.get("webVideoUrl"),
        data.get("url"),
        meta.get("url"),
        data.get("inputUrl"),
        url,
    )

    return EnrichmentResult(
        url=resolved_url,
        title=title[:200],
        caption=caption,
        transcript=transcript,
        author=author,
        platform=platform,
        hashtags=hashtags[:20],
        raw=data,
    )


def normalize_dataset(
    url: str,
    platform: str,
    items: list[dict[str, Any]] | None,
) -> EnrichmentResult:
    rows = _as_list(items) if not isinstance(items, list) else [
        x for x in items if isinstance(x, dict)
    ]
    if not rows and isinstance(items, list) and items:
        # already filtered
        pass
    first = rows[0] if rows else None
    return normalize_actor_item(url, platform, first)
