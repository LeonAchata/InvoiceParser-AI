"""Zero-config history of saved documents, stored in SQLite."""

import asyncio
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    filename        TEXT,
    document_type   TEXT,
    document_number TEXT,
    issue_date      TEXT,
    issuer_name     TEXT,
    customer_name   TEXT,
    currency        TEXT,
    total           REAL,
    data            TEXT NOT NULL
);
"""

SUMMARY_COLUMNS = (
    "id, created_at, filename, document_type, document_number, issue_date, issuer_name, customer_name, currency, total"
)


class DocumentStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commits or rolls back
                yield conn
        finally:
            conn.close()

    def _save(self, data: dict[str, Any], filename: str | None) -> int:
        issuer, customer = data.get("issuer") or {}, data.get("customer") or {}
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO documents (created_at, filename, document_type, document_number, issue_date,"
                " issuer_name, customer_name, currency, total, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    filename,
                    data.get("document_type"),
                    data.get("document_number"),
                    data.get("issue_date"),
                    issuer.get("name"),
                    customer.get("name"),
                    data.get("currency"),
                    data.get("total"),
                    json.dumps(data, ensure_ascii=False),
                ),
            )
            return cur.lastrowid

    def _list(self, limit: int, offset: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {SUMMARY_COLUMNS} FROM documents ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [dict(r) for r in rows]

    def _get(self, doc_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["data"] = json.loads(result["data"])
        return result

    def _delete(self, doc_id: int) -> bool:
        with self._connect() as conn:
            return conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,)).rowcount > 0

    # Async wrappers so the event loop never blocks on disk I/O.
    async def save(self, data: dict[str, Any], filename: str | None = None) -> int:
        return await asyncio.to_thread(self._save, data, filename)

    async def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list, limit, offset)

    async def get(self, doc_id: int) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get, doc_id)

    async def delete(self, doc_id: int) -> bool:
        return await asyncio.to_thread(self._delete, doc_id)
