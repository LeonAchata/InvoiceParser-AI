import asyncio
import json

import httpx
from openai import AsyncOpenAI

from app.loaders import load_document
from app.pipeline import llm
from tests.conftest import FAKE_EXTRACTION


def fake_openai(captured: list) -> AsyncOpenAI:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        content = "```json\n" + json.dumps(FAKE_EXTRACTION) + "\n```"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-test",
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}
                ],
                "usage": {"prompt_tokens": 900, "completion_tokens": 300, "total_tokens": 1200},
            },
        )

    return AsyncOpenAI(api_key="sk-test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_request_contains_text_and_images(monkeypatch, sample):
    captured: list = []
    monkeypatch.setattr(llm, "get_client", lambda: fake_openai(captured))
    doc = load_document(sample("boleta-foto.jpg"), "boleta.jpg")

    data, usage = asyncio.run(llm.extract_with_llm(doc, ""))

    assert data["document_number"] == "F001-00004821"  # parsed despite the ``` fences
    assert usage == {"prompt": 900, "completion": 300, "total": 1200}
    body = captured[0]
    assert body["response_format"] == {"type": "json_object"}
    parts = body["messages"][1]["content"]
    assert parts[0]["type"] == "text" and "provided as images" in parts[0]["text"]
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_parse_json_tolerates_noise():
    assert llm.parse_json('Sure! {"a": 1} hope it helps') == {"a": 1}
