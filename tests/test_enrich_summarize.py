"""Summary JSON parsing + mocked OpenRouter."""

from __future__ import annotations

import httpx

from nudge.archive.normalize import EnrichmentResult
from nudge.archive.summarize import parse_summary_json, summarize_enrichment


def test_parse_summary_json_clean():
    raw = '{"title":"Короткий заголовок","summary":"Коротко о деле.","takeaway":"Сохраняй сразу."}'
    s = parse_summary_json(raw)
    assert s.title.startswith("Короткий")
    assert s.summary.startswith("Коротко")
    assert "Сохраняй" in s.takeaway
    assert s.tags == []


def test_parse_summary_json_fenced():
    raw = 'Вот JSON:\n```json\n{"title":"Заг","summary":"Да","takeaway":"б"}\n```'
    s = parse_summary_json(raw)
    assert s.title == "Заг"
    assert s.summary == "Да"


def test_summarize_with_mock_transport():
    item = EnrichmentResult(
        url="https://www.tiktok.com/@u/video/1",
        title="t",
        caption="Длинный caption про продукт и идею ролика",
        transcript="spoken words here about the topic in enough length for summary",
        platform="tiktok",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "openrouter.ai" in str(request.url)
        body = (
            '{"choices":[{"message":{"content":'
            '"{\\"title\\":\\"Заголовок\\",\\"summary\\":\\"Выжимка.\\",\\"takeaway\\":\\"Одно.\\"}"'
            "}}]}"
        )
        return httpx.Response(200, content=body.encode())

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        s = summarize_enrichment(item, client=client, api_key="sk-test", model="test/model")
    assert s.title == "Заголовок"
    assert s.summary == "Выжимка."
    assert s.tags == []
