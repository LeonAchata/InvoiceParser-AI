"""In-memory background job manager (good enough for a single-process demo)."""

import asyncio
import logging
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from app.pipeline import STEPS, LLMNotConfiguredError, PipelineError, run_pipeline

logger = logging.getLogger(__name__)
MAX_JOBS = 200


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class JobManager:
    def __init__(self) -> None:
        self.jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._tasks: set[asyncio.Task] = set()

    def create(self, data: bytes, filename: str) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "filename": filename,
            "size_bytes": len(data),
            "status": "queued",
            "step": None,
            "steps": [{"id": k, "label": v} for k, v in STEPS.items()],
            "created_at": _now(),
            "finished_at": None,
            "result": None,
            "error": None,
        }
        self.jobs[job_id] = job
        while len(self.jobs) > MAX_JOBS:
            self.jobs.popitem(last=False)

        task = asyncio.create_task(self._run(job, data))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        job["_task"] = task
        return job

    async def _run(self, job: dict[str, Any], data: bytes) -> None:
        async def on_step(step: str) -> None:
            job["status"], job["step"] = "processing", step

        try:
            job["result"] = await run_pipeline(data, job["filename"], on_step)
            job["status"] = "completed"
        except (PipelineError, LLMNotConfiguredError) as exc:
            job["status"], job["error"] = "failed", str(exc)
        except Exception as exc:  # unexpected: log the full traceback, show a short message
            logger.exception("Job %s failed", job["id"])
            job["status"], job["error"] = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            job["finished_at"] = _now()

    async def wait(self, job: dict[str, Any], timeout: float) -> None:
        await asyncio.wait_for(asyncio.shield(job["_task"]), timeout)

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    @staticmethod
    def public(job: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in job.items() if not k.startswith("_")}
