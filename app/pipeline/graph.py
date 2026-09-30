"""LangGraph pipeline: load -> clean -> extract (LLM) -> validate."""

import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.config import get_settings
from app.loaders import LoadedDocument, load_document
from app.pipeline.llm import extract_with_llm
from app.pipeline.validation import completeness, run_checks
from app.schemas import InvoiceData

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """An expected failure with a message that is safe to show to the user."""


class PipelineState(TypedDict, total=False):
    filename: str
    data: bytes
    document: LoadedDocument
    text: str
    raw_output: dict[str, Any]
    invoice: InvoiceData
    checks: list[dict[str, Any]]
    completeness: float
    usage: dict[str, int]
    timings: dict[str, float]


# Human-readable labels, also used by the frontend progress stepper.
STEPS = {
    "load": "Reading document",
    "clean": "Normalizing text",
    "extract": "Extracting fields with AI",
    "validate": "Validating results",
}


def _timed(name: str, fn: Callable[[PipelineState], Awaitable[dict]]):
    async def node(state: PipelineState) -> dict:
        started = time.perf_counter()
        update = await fn(state)
        timings = dict(state.get("timings", {}))
        timings[name] = round(time.perf_counter() - started, 3)
        return {**update, "timings": timings}

    return node


async def load_node(state: PipelineState) -> dict:
    settings = get_settings()
    try:
        doc = load_document(
            state["data"], state["filename"], max_pages=settings.max_pages, max_side=settings.image_max_side
        )
    except ValueError as exc:
        raise PipelineError(str(exc)) from exc
    if not doc.has_content:
        raise PipelineError("No readable content was found in the document")
    logger.info("Loaded %s as %s via %s", state["filename"], doc.format, doc.method)
    return {"document": doc, "data": b""}  # drop raw bytes as soon as possible


async def clean_node(state: PipelineState) -> dict:
    text = state["document"].text
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return {"text": text[: get_settings().max_text_chars]}


async def extract_node(state: PipelineState) -> dict:
    raw, usage = await extract_with_llm(state["document"], state["text"])
    return {"raw_output": raw, "usage": usage}


async def validate_node(state: PipelineState) -> dict:
    invoice = InvoiceData.model_validate(state["raw_output"])
    return {
        "invoice": invoice,
        "checks": [c.model_dump() for c in run_checks(invoice)],
        "completeness": completeness(invoice),
    }


def build_graph():
    graph = StateGraph(PipelineState)
    for name, fn in (
        ("load", load_node),
        ("clean", clean_node),
        ("extract", extract_node),
        ("validate", validate_node),
    ):
        graph.add_node(name, _timed(name, fn))
    graph.set_entry_point("load")
    graph.add_edge("load", "clean")
    graph.add_edge("clean", "extract")
    graph.add_edge("extract", "validate")
    graph.add_edge("validate", END)
    return graph.compile()


_graph = None
StepCallback = Callable[[str], Awaitable[None]]


async def run_pipeline(data: bytes, filename: str, on_step: StepCallback | None = None) -> dict[str, Any]:
    """Run the graph and return a JSON-serializable result."""
    global _graph
    _graph = _graph or build_graph()

    state: dict[str, Any] = {"filename": filename, "data": data, "timings": {}}
    if on_step:
        await on_step("load")
    order = list(STEPS)
    async for chunk in _graph.astream(state, stream_mode="updates"):
        for node, update in chunk.items():
            state.update(update or {})
            nxt = order.index(node) + 1
            if on_step and nxt < len(order):
                await on_step(order[nxt])

    doc: LoadedDocument = state["document"]
    return {
        "data": state["invoice"].model_dump(),
        "checks": state["checks"],
        "completeness": state["completeness"],
        "document": {
            "filename": filename,
            "format": doc.format,
            "method": doc.method,
            "pages": doc.pages,
            "images_sent": len(doc.images),
            "text_preview": state["text"][:20_000],
            "meta": {k: v for k, v in doc.meta.items() if isinstance(v, (str, int, float, bool, list))},
        },
        "usage": {**state.get("usage", {}), "model": get_settings().llm_model},
        "timings": state["timings"],
    }
