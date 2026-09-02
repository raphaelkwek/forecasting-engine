"""An append-only log of schema validation runs.

Every validation is recorded whether it passed or failed, with the full issue
detail kept as JSON so downstream work — the data quality report above all —
can reuse it without re-running the check.

Like the upload log, this is an event log: validating the same file twice is
two rows. What was checked and when is the point.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from forecasting_engine.ingest.validation import ValidationResult
from forecasting_engine.store._db import DEFAULT_DB_PATH, connect

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS validations (
    sha256         TEXT      NOT NULL,
    filename       TEXT      NOT NULL,
    passed         BOOLEAN   NOT NULL,
    issue_count    BIGINT    NOT NULL,
    blocking_count BIGINT    NOT NULL,
    warning_count  BIGINT    NOT NULL,
    issues         TEXT      NOT NULL,
    checked_at     TIMESTAMP NOT NULL
)
"""

_SELECT = (
    "SELECT sha256, filename, passed, issue_count, blocking_count, "
    "warning_count, issues, checked_at FROM validations"
)


@dataclass(frozen=True)
class ValidationRecord:
    """One row of the log."""

    sha256: str
    filename: str
    passed: bool
    issue_count: int
    blocking_count: int
    warning_count: int
    issues: list[dict[str, Any]]
    checked_at: datetime


def record_validation(
    result: ValidationResult,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    checked_at: datetime | None = None,
) -> ValidationRecord:
    """Append ``result`` to the log and return the row that was written."""
    summary = result.summary
    record = ValidationRecord(
        sha256=result.source.sha256,
        filename=result.source.name,
        passed=result.passed,
        issue_count=summary["issue_count"],
        blocking_count=summary["blocking_count"],
        warning_count=summary["warning_count"],
        issues=result.as_records(),
        checked_at=checked_at or result.checked_at,
    )
    with connect(db_path, _CREATE_TABLE) as conn:
        conn.execute(
            "INSERT INTO validations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                record.sha256,
                record.filename,
                record.passed,
                record.issue_count,
                record.blocking_count,
                record.warning_count,
                json.dumps(record.issues),
                record.checked_at,
            ],
        )
    return record


def recent_validations(
    limit: int = 20, *, db_path: Path = DEFAULT_DB_PATH
) -> list[ValidationRecord]:
    """The most recent validation runs, newest first."""
    with connect(db_path, _CREATE_TABLE) as conn:
        rows = conn.execute(
            f"{_SELECT} ORDER BY checked_at DESC LIMIT ?", [limit]
        ).fetchall()
    return [_to_record(row) for row in rows]


def latest_validation(
    sha256: str, *, db_path: Path = DEFAULT_DB_PATH
) -> ValidationRecord | None:
    """The most recent validation of one file, or None if it was never checked."""
    with connect(db_path, _CREATE_TABLE) as conn:
        row = conn.execute(
            f"{_SELECT} WHERE sha256 = ? ORDER BY checked_at DESC LIMIT 1", [sha256]
        ).fetchone()
    return _to_record(row) if row else None


def _to_record(row: tuple[Any, ...]) -> ValidationRecord:
    *head, issues, checked_at = row
    return ValidationRecord(*head, issues=json.loads(issues), checked_at=checked_at)
