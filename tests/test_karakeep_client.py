"""Karakeep client payload tests with MockTransport."""

from __future__ import annotations

import json

import httpx

from nudge.archive.karakeep import (
    create_bookmark,
    format_archive_ack,
    parse_tag_list,
    replace_tags,
    wait_for_tags,
)


def test_parse_tag_list():
    assert parse_tag_list("gpt, Claude, #DeepSWE") == ["gpt", "Claude", "DeepSWE"]
    assert parse_tag_list("a; b\nc") == ["a", "b", "c"]
    assert parse_tag_list("-") == []
    assert parse_tag_list("нет") == []
    assert parse_tag_list("A, a, B") == ["A", "B"]


def test_format_archive_ack_mentions_reply():
    text = format_archive_ack("Заголовок", ["gpt", "Claude"])
    assert "Заголовок" in text
    assert "gpt" in text
    assert "через запятую" in text


def test_create_link_bookmark_payload():
    posts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        posts.append(
            {
                "url": str(request.url),
                "auth": request.headers.get("Authorization"),
                "body": body,
                "method": request.method,
            }
        )
        if request.method == "POST" and request.url.path.endswith("/bookmarks"):
            return httpx.Response(201, json={"id": "bm1", "type": "link"})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        data = create_bookmark(
            url="https://example.com",
            title="Ex",
            note="n",
            summary="s",
            tags=["t1"],
            api_url="http://kk.test",
            api_key="ak_test",
            client=client,
        )
    assert data["id"] == "bm1"
    create = next(p for p in posts if p["method"] == "POST" and p["url"].endswith("/bookmarks"))
    assert create["auth"] == "Bearer ak_test"
    assert b"https://example.com" in create["body"]


def test_create_text_bookmark():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": "bm2", "type": "text"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        data = create_bookmark(
            text="секретная панель — пароль в менеджере",
            title="Доступ VPS",
            api_url="http://kk.test",
            api_key="ak_test",
            client=client,
        )
    assert data["id"] == "bm2"


def test_wait_for_tags_until_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                json={"id": "bm", "taggingStatus": "pending", "tags": []},
            )
        return httpx.Response(
            200,
            json={
                "id": "bm",
                "taggingStatus": "success",
                "tags": [{"id": "t1", "name": "gpt", "attachedBy": "ai"}],
            },
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        names = wait_for_tags(
            "bm",
            timeout_s=5,
            poll_s=0.01,
            api_url="http://kk.test",
            api_key="ak",
            client=client,
        )
    assert names == ["gpt"]
    assert calls["n"] >= 2


def test_replace_tags_detaches_missing_and_attaches_new():
    ops: list[tuple[str, dict]] = []
    state = {
        "tags": [
            {"id": "1", "name": "old"},
            {"id": "2", "name": "keep"},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.method
        path = request.url.path
        body = json.loads(request.content.decode()) if request.content else {}
        if method == "GET":
            return httpx.Response(200, json={"id": "bm", "tags": state["tags"]})
        if method == "DELETE" and path.endswith("/tags"):
            ops.append(("DELETE", body))
            detach_ids = {t.get("tagId") for t in body.get("tags", [])}
            state["tags"] = [t for t in state["tags"] if t["id"] not in detach_ids]
            return httpx.Response(200, json={"detached": list(detach_ids)})
        if method == "POST" and path.endswith("/tags"):
            ops.append(("POST", body))
            for t in body.get("tags", []):
                name = t["tagName"]
                state["tags"].append({"id": f"n-{name}", "name": name})
            return httpx.Response(200, json={"attached": ["x"]})
        return httpx.Response(500, json={"error": "unexpected"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        final = replace_tags(
            "bm",
            ["keep", "new"],
            api_url="http://kk.test",
            api_key="ak",
            client=client,
        )
    assert ops[0][0] == "DELETE"
    assert ops[0][1]["tags"] == [{"tagId": "1"}]
    assert ops[1][0] == "POST"
    assert ops[1][1]["tags"] == [{"tagName": "new"}]
    assert final == ["keep", "new"]
