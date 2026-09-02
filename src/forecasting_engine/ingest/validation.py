"""Validating an uploaded file against the documented schema, and gating on it.

Upload validation (``upload.py``) asks whether a file is readable at all. This
module asks the next question: does what we read match the contract in
``docs/data-specification.md``?

The answer separates two classes of problem, following the "How violations are
treated" section of that document:

**Blocking.** A missing column, an unparseable date, a non-numeric value in a
numeric column. The file cannot be interpreted, so the pipeline stops.

**Warning.** Out-of-order rows, duplicate dates, values outside the documented
ranges. These are repaired or retained downstream and reported either way. A
genuine market dislocation looks a lot like an outlier, so refusing the file
would hide exactly the events the model most needs to see.

Passing produces a ``ValidatedUpload``. Data preparation will take that type
rather than a bare frame, so there is no type-legal way to prepare a file that
was never checked — the same construction the architecture uses to keep
unlagged data out of models.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from forecasting_engine.ingest.provenance import SourceFile
from forecasting_engine.ingest.schema import SchemaIssue, blocking, validate
from forecasting_engine.ingest.upload import AcceptedUpload


@dataclass(frozen=True)
class ValidationResult:
    """What validating one file found. Structured for reuse downstream."""

    source: SourceFile
    issues: tuple[SchemaIssue, ...]
    checked_at: datetime

    @property
    def blocking(self) -> tuple[SchemaIssue, ...]:
        """Issues that make the file unusable."""
        return tuple(blocking(list(self.issues)))

    @property
    def warnings(self) -> tuple[SchemaIssue, ...]:
        """Issues worth reporting that do not stop the pipeline."""
        stoppers = set(self.blocking)
        return tuple(issue for issue in self.issues if issue not in stoppers)

    @property
    def passed(self) -> bool:
        """Whether the pipeline may proceed. Warnings do not prevent this."""
        return not self.blocking

    @property
    def is_clean(self) -> bool:
        """Whether the file matched the contract exactly, warnings included."""
        return not self.issues

    @property
    def missing_columns(self) -> tuple[str, ...]:
        """Required columns the file does not have, named for the error output."""
        return tuple(i.column for i in self.issues if i.kind == "missing_column")

    @property
    def summary(self) -> dict[str, Any]:
        """Counts, for logging and for the data quality report."""
        return {
            "passed": self.passed,
            "issue_count": len(self.issues),
            "blocking_count": len(self.blocking),
            "warning_count": len(self.warnings),
        }

    def as_records(self) -> list[dict[str, Any]]:
        """Every issue as plain data, ready to serialise into the run store."""
        stoppers = set(self.blocking)
        return [
            {
                "kind": issue.kind,
                "column": issue.column,
                "detail": issue.detail,
                "count": issue.count,
                "rows": list(issue.rows),
                "blocking": issue in stoppers,
            }
            for issue in self.issues
        ]

    def describe(self) -> str:
        """One line per problem, each naming its column and lines."""
        return "\n".join(f"{issue.location}: {issue.detail}" for issue in self.issues)


@dataclass(frozen=True)
class ValidatedUpload:
    """An upload that matched the schema. The entry token for data preparation."""

    accepted: AcceptedUpload
    result: ValidationResult

    @property
    def frame(self) -> pd.DataFrame:
        return self.accepted.frame

    @property
    def source(self) -> SourceFile:
        return self.accepted.source


class ValidationFailed(Exception):
    """Raised to halt the pipeline when a file does not match the schema."""

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        self.message = _failure_message(result)
        super().__init__(self.message)


def validate_upload(
    accepted: AcceptedUpload, *, checked_at: datetime | None = None
) -> ValidationResult:
    """Check ``accepted`` against the schema. Never raises — inspect the result."""
    return ValidationResult(
        source=accepted.source,
        issues=tuple(validate(accepted.frame)),
        checked_at=checked_at or datetime.now(),
        )


def require_valid(accepted: AcceptedUpload, result: ValidationResult) -> ValidatedUpload:
    """Return the token data preparation needs, or raise ``ValidationFailed``.

    This is the halt: everything downstream takes a ``ValidatedUpload``, so a
    file with blocking issues has no way through.
    """
    if not result.passed:
        raise ValidationFailed(result)
    return ValidatedUpload(accepted=accepted, result=result)


def _failure_message(result: ValidationResult) -> str:
    """Say what is wrong and where, in the order a reader would fix it."""
    missing = result.missing_columns
    parts: list[str] = []
    if missing:
        named = ", ".join(repr(name) for name in missing)
        parts.append(f"missing required column{'s' if len(missing) > 1 else ''}: {named}")

    others = [i for i in result.blocking if i.kind != "missing_column"]
    parts.extend(f"{issue.detail} in {issue.location}" for issue in others)

    return f"{result.source.name} does not match the schema — " + "; ".join(parts) + "."
