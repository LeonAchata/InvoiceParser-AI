"""FastAPI application: REST API under /api and the web UI at /."""

import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import __version__
from app.config import get_settings
from app.excel import build_workbook
from app.jobs import JobManager
from app.loaders import detect_format, supported_formats
from app.schemas import InvoiceData
from app.storage import DocumentStore

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"
SAMPLES_DIR = ROOT / "samples"

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.jobs = JobManager()
    app.state.store = DocumentStore(settings.db_file)
    if not settings.llm_configured:
        logging.getLogger("app").warning("OPENAI_API_KEY is not set: extraction requests will fail")
    yield


app = FastAPI(
    title="InvoiceParser AI",
    description="Turn invoices, receipts and tickets in any format into structured, validated data.",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- extraction


@app.post("/api/extract", tags=["extraction"])
async def extract(
    file: UploadFile = File(..., description="Invoice / receipt in any supported format"),
    wait: bool = Query(False, description="Block until the result is ready instead of returning a job id"),
) -> dict[str, Any]:
    """Upload a document and start the extraction pipeline."""
    data = await file.read(settings.max_file_size_bytes + 1)
    if not data:
        raise HTTPException(400, "The file is empty")
    if len(data) > settings.max_file_size_bytes:
        raise HTTPException(413, f"File too large. The limit is {settings.max_file_size_mb} MB")
    filename = file.filename or "document"
    if not detect_format(filename, data):
        raise HTTPException(415, f"Unsupported file type '{Path(filename).suffix}'. See GET /api/formats")
    if not settings.llm_configured:
        raise HTTPException(503, "OPENAI_API_KEY is not configured on the server")

    jobs: JobManager = app.state.jobs
    job = jobs.create(data, filename)
    if wait:
        try:
            await jobs.wait(job, timeout=settings.request_timeout * 2)
        except TimeoutError:
            pass
    return jobs.public(job)


@app.get("/api/jobs/{job_id}", tags=["extraction"])
async def get_job(job_id: str) -> dict[str, Any]:
    """Poll a job: status is queued | processing | completed | failed. `result` is set once completed."""
    job = app.state.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return JobManager.public(job)


@app.get("/api/formats", tags=["meta"])
async def formats() -> dict[str, Any]:
    return {"formats": supported_formats(), "max_file_size_mb": settings.max_file_size_mb}


@app.get("/api/health", tags=["meta"])
async def health() -> dict[str, Any]:
    jobs: JobManager = app.state.jobs
    return {
        "status": "ok",
        "version": __version__,
        "llm_configured": settings.llm_configured,
        "model": settings.llm_model,
        "active_jobs": sum(j["status"] in ("queued", "processing") for j in jobs.jobs.values()),
    }


# ---------------------------------------------------------------- export & history


class DocumentIn(BaseModel):
    data: InvoiceData
    filename: str | None = None


def _safe_name(name: str | None) -> str:
    stem = Path(name or "document").stem
    return re.sub(r"[^\w\-]+", "_", stem).strip("_") or "document"


@app.post("/api/export/xlsx", tags=["export"])
async def export_xlsx(payload: DocumentIn) -> StreamingResponse:
    buffer = build_workbook(payload.data.model_dump(), payload.filename)
    name = f"{_safe_name(payload.filename)}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/api/documents", tags=["history"])
async def list_documents(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    return {"items": await app.state.store.list(limit, offset), "limit": limit, "offset": offset}


@app.post("/api/documents", status_code=201, tags=["history"])
async def save_document(payload: DocumentIn) -> dict[str, Any]:
    doc_id = await app.state.store.save(payload.data.model_dump(), payload.filename)
    return {"id": doc_id}


@app.get("/api/documents/{doc_id}", tags=["history"])
async def get_document(doc_id: int) -> dict[str, Any]:
    doc = await app.state.store.get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@app.delete("/api/documents/{doc_id}", status_code=204, tags=["history"])
async def delete_document(doc_id: int) -> None:
    if not await app.state.store.delete(doc_id):
        raise HTTPException(404, "Document not found")


# ---------------------------------------------------------------- samples & UI


@app.get("/api/samples", tags=["meta"])
async def list_samples() -> list[dict[str, Any]]:
    if not SAMPLES_DIR.is_dir():
        return []
    return [
        {
            "name": p.name,
            "format": detect_format(p.name, b""),
            "url": f"/samples/{p.name}",
            "size_bytes": p.stat().st_size,
        }
        for p in sorted(SAMPLES_DIR.iterdir())
        if p.is_file() and detect_format(p.name, b"")
    ]


if SAMPLES_DIR.is_dir():
    app.mount("/samples", StaticFiles(directory=SAMPLES_DIR), name="samples")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
