"""Calls a (vision-capable) OpenAI-compatible chat model and parses its JSON answer."""

import base64
import json
import re
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.loaders import LoadedDocument
from app.pipeline.prompts import SYSTEM_PROMPT, build_user_prompt


class LLMNotConfiguredError(RuntimeError):
    pass


@lru_cache
def get_client() -> AsyncOpenAI:
    settings = get_settings()
    if not settings.llm_configured:
        raise LLMNotConfiguredError("OPENAI_API_KEY is not set. Add it to your .env file.")
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.request_timeout,
        max_retries=settings.llm_max_retries,
    )


def build_messages(doc: LoadedDocument, text: str) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": build_user_prompt(text)}]
    for image in doc.images:
        url = f"data:{image.mime};base64,{base64.b64encode(image.data).decode()}"
        content.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]


def parse_json(content: str) -> dict[str, Any]:
    content = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", content, re.S)
    if fenced:
        content = fenced.group(1)
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("The model did not return a JSON object")
    return json.loads(content[start : end + 1])


async def extract_with_llm(doc: LoadedDocument, text: str) -> tuple[dict[str, Any], dict[str, int]]:
    settings = get_settings()
    params: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": build_messages(doc, text),
        "response_format": {"type": "json_object"},
        "max_completion_tokens": settings.llm_max_output_tokens,
    }
    if settings.llm_temperature is not None:
        params["temperature"] = settings.llm_temperature

    response = await get_client().chat.completions.create(**params)
    usage = response.usage
    tokens = {
        "prompt": usage.prompt_tokens if usage else 0,
        "completion": usage.completion_tokens if usage else 0,
        "total": usage.total_tokens if usage else 0,
    }
    return parse_json(response.choices[0].message.content or ""), tokens
