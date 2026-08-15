"""Karakeep REST client (bookmarks + tags)."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0)
_TAG_SPLIT_RE = re.compile(r"[,;\n]+")


class KarakeepError(RuntimeError):
    pass


def _base_and_key(
    api_url: str | None = None,
    api_key: str | None = None,
) -> tuple[str, str]:
    settings = get_settings()
    base = (api_url or settings.karakeep_api_url).rstrip("/")
    key = api_key if api_key is not None else settings.karakeep_api_key
    if not base:
        raise KarakeepError("KARAKEEP_API_URL is empty")
    if not key:
        raise KarakeepError("KARAKEEP_API_KEY is empty")
    return base, key


def create_bookmark(
    *,
    url: str | None = None,
    title: str = "",
    note: str = "",
    summary: str = "",
    text: str | None = None,
    tags: list[str] | None = None,
    api_url: str | None = None,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Create link or text bookmark. Returns API JSON. Raises KarakeepError."""
    base, key = _base_and_key(api_url, api_key)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    if text is not None and not url:
        body: dict[str, Any] = {"type": "text", "text": text}
        if title:
            body["title"] = title
    else:
        if not url:
            raise KarakeepError("url required for link bookmark")
        body = {"type": "link", "url": url}
        if title:
            body["title"] = title
        # Karakeep fields vary by version — send common optional ones
        if note:
            body["note"] = note
        if summary:
            body["summary"] = summary

    own = client is None
    http = client or httpx.Client(timeout=_TIMEOUT)
    try:
        resp = http.post(f"{base}/api/v1/bookmarks", headers=headers, json=body)
        if resp.status_code >= 400:
            # Retry without note/summary if schema rejects them
            if resp.status_code == 400 and (note or summary):
                slim = {"type": body["type"]}
                if body["type"] == "link":
                    slim["url"] = url
                    if title:
                        slim["title"] = title
                else:
                    slim["text"] = text
                    if title:
                        slim["title"] = title
                resp = http.post(f"{base}/api/v1/bookmarks", headers=headers, json=slim)
            if resp.status_code >= 400:
                raise KarakeepError(f"create bookmark: {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        bookmark_id = data.get("id")
        if bookmark_id and tags:
            _attach_tags(http, base, headers, bookmark_id, tags)
            # Best-effort: also PATCH note/summary into bookmark if first create dropped them
            if note or summary:
                patch: dict[str, Any] = {}
                if note:
                    patch["note"] = note
                if summary:
                    patch["summary"] = summary
                try:
                    http.patch(
                        f"{base}/api/v1/bookmarks/{bookmark_id}",
                        headers=headers,
                        json=patch,
                    )
                except Exception:
                    log.debug("optional bookmark patch failed", exc_info=True)
        return data
    finally:
        if own:
            http.close()


def parse_tag_list(text: str) -> list[str]:
    """Comma/semicolon/newline list → clean tag names. «-» / «нет» → empty (clear)."""
    raw = (text or "").strip()
    if not raw:
        return []
    if raw.lower() in {"-", "—", "нет", "очистить", "без тегов"}:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in _TAG_SPLIT_RE.split(raw):
        name = part.strip().lstrip("#").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def get_bookmark(
    bookmark_id: str,
    *,
    api_url: str | None = None,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    base, key = _base_and_key(api_url, api_key)
    headers = {"Authorization": f"Bearer {key}"}
    own = client is None
    http = client or httpx.Client(timeout=_TIMEOUT)
    try:
        resp = http.get(f"{base}/api/v1/bookmarks/{bookmark_id}", headers=headers)
        if resp.status_code >= 400:
            raise KarakeepError(f"get bookmark: {resp.status_code} {resp.text[:300]}")
        return resp.json()
    finally:
        if own:
            http.close()


def tag_names_from_bookmark(data: dict[str, Any]) -> list[str]:
    tags = data.get("tags") or []
    names: list[str] = []
    for t in tags:
        if isinstance(t, dict) and t.get("name"):
            names.append(str(t["name"]))
        elif isinstance(t, str) and t.strip():
            names.append(t.strip())
    return names


def wait_for_tags(
    bookmark_id: str,
    *,
    timeout_s: float = 25.0,
    poll_s: float = 1.5,
    api_url: str | None = None,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    """Poll until Karakeep AI tagging finishes (or timeout)."""
    deadline = time.monotonic() + timeout_s
    last: list[str] = []
    own = client is None
    http = client or httpx.Client(timeout=_TIMEOUT)
    try:
        while True:
            data = get_bookmark(
                bookmark_id, api_url=api_url, api_key=api_key, client=http
            )
            last = tag_names_from_bookmark(data)
            status = (data.get("taggingStatus") or "").lower()
            if status in {"success", "failure", "failed"}:
                return last
            if time.monotonic() >= deadline:
                return last
            # pending / unknown — keep polling
            time.sleep(poll_s)
    finally:
        if own:
            http.close()


def replace_tags(
    bookmark_id: str,
    tag_names: list[str],
    *,
    api_url: str | None = None,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    """Set exact tag set: attach missing, detach the rest. Returns final names."""
    desired: list[str] = []
    seen: set[str] = set()
    for t in tag_names:
        name = (t or "").strip().lstrip("#").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        desired.append(name)

    base, key = _base_and_key(api_url, api_key)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    own = client is None
    http = client or httpx.Client(timeout=_TIMEOUT)
    try:
        data = get_bookmark(bookmark_id, api_url=api_url, api_key=api_key, client=http)
        current = data.get("tags") or []
        current_by_cf: dict[str, dict[str, Any]] = {}
        for t in current:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            current_by_cf[str(t["name"]).casefold()] = t

        desired_cf = {n.casefold() for n in desired}
        to_detach = [t for cf, t in current_by_cf.items() if cf not in desired_cf]
        to_attach = [n for n in desired if n.casefold() not in current_by_cf]

        tags_path = f"{base}/api/v1/bookmarks/{bookmark_id}/tags"
        if to_detach:
            payload = {
                "tags": [
                    {"tagId": t["id"]} if t.get("id") else {"tagName": t["name"]}
                    for t in to_detach
                ]
            }
            resp = http.request("DELETE", tags_path, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise KarakeepError(
                    f"detach tags: {resp.status_code} {resp.text[:300]}"
                )
        if to_attach:
            payload = {"tags": [{"tagName": n} for n in to_attach]}
            resp = http.post(tags_path, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise KarakeepError(
                    f"attach tags: {resp.status_code} {resp.text[:300]}"
                )

        final = get_bookmark(bookmark_id, api_url=api_url, api_key=api_key, client=http)
        return tag_names_from_bookmark(final)
    finally:
        if own:
            http.close()


def _attach_tags(
    http: httpx.Client,
    base: str,
    headers: dict[str, str],
    bookmark_id: str,
    tags: list[str],
) -> None:
    """Attach tags; ignore failures (API shape differs across versions)."""
    clean = [t.strip().lstrip("#") for t in tags if t and t.strip()]
    if not clean:
        return
    payloads = [
        {"tags": [{"tagName": t} for t in clean]},
        {"tags": clean},
    ]
    for path in (
        f"{base}/api/v1/bookmarks/{bookmark_id}/tags",
        f"{base}/api/v1/bookmarks/{bookmark_id}/tag",
    ):
        for payload in payloads:
            try:
                r = http.post(path, headers=headers, json=payload)
                if r.status_code < 400:
                    return
            except Exception:
                log.debug("tag attach attempt failed", exc_info=True)


def format_archive_ack(title: str, tags: list[str]) -> str:
    title_show = (title or "без названия").strip()[:80]
    if tags:
        tag_line = ", ".join(tags)
    else:
        tag_line = "(пока нет)"
    return (
        f"✓ в архиве: «{title_show}»\n"
        f"теги: {tag_line}\n"
        "↩️ ответь на это сообщение списком через запятую — заменю теги "
        "(какие не укажешь — сниму). «-» = без тегов."
    )
