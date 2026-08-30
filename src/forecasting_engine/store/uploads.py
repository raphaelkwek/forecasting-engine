"""An append-only log of upload attempts that succeeded.

Deliberately narrow. The architecture design puts full run history in
``store/runs.py`` in Sprint 6; this module records uploads and nothing else, so
that it does not pre-commit the run schema that sprint owns.

The table is an event log: the same file uploaded twice is two rows. What
happened and when is the point, not which distinct files exist.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb

from forecasting_engine.ingest.upload import AcceptedUpload

#: Gitignored, because ``data/`` is.
DEFAULT_DB_PATH: Path = Path("data/forecasting.duckdb")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS uploads (
    sha256      TEXT      NOT NULL,
    filename    TEXT      NOT NULL,
    size_bytes  BIGINT    NOT NULL,
    row_count   BIGINT    NOT NULL,
    uploaded_at TIMESTAMP NOT NULL
)
"""


@dataclass(frozen=True)
class UploadRecord:
    """One row of the log."""

    sha256: str
    filename: str
    size_bytes: int
    row_count: int
    uploaded_at: datetime


def record_upload(
    accepted: AcceptedUpload,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    uploaded_at: datetime | None = None,
) -> UploadRecord:
    """Append ``accepted`` to the log and return the row that was written.

    ``uploaded_at`` defaults to now; pass it explicitly to keep tests
    deterministic.
    """
    record = UploadRecord(
        sha256=accepted.source.sha256,
        filename=accepted.source.name,
        size_bytes=accepted.source.size_bytes,
        row_count=accepted.row_count,
        uploaded_at=uploaded_at or datetime.now(),
    )
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO uploads VALUES (?, ?, ?, ?, ?)",
            [
                record.sha256,
                record.filename,
                record.size_bytes,
                record.row_count,
                record.uploaded_at,
            ],
        )
    return record


def recent_uploads(limit: int = 20, *, db_path: Path = DEFAULT_DB_PATH) -> list[UploadRecord]:
    """The most recent uploads, newest first."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT sha256, filename, size_bytes, row_count, uploaded_at "
            "FROM uploads ORDER BY uploaded_at DESC LIMIT ?",
            [limit],
        ).fetchall()
    return [UploadRecord(*row) for row in rows]


@contextlib.contextmanager
def _connect(db_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open ``db_path``, creating the file and the table if they are absent."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(_CREATE_TABLE)
        yield conn
    finally:
        conn.close()
