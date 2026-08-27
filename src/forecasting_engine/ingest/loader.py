"""CSV to validated in-memory frame.

Repairs what is safely repairable (ordering, duplicate dates), reports what is
not, and refuses outright to hand back a file that is structurally broken.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from forecasting_engine.ingest import schema
from forecasting_engine.ingest.provenance import SourceFile


class SchemaError(Exception):
    """Raised when a file violates the contract in a way that cannot be repaired."""


@dataclass(frozen=True)
class RawFrame:
    """A loaded file: date-indexed, sorted, deduplicated, not yet lagged."""

    frame: pd.DataFrame
    source: SourceFile
    issues: tuple[schema.SchemaIssue, ...]


def load(path: str | Path, *, strict: bool = True) -> RawFrame:
    """Read ``path`` and validate it against the column contract.

    With ``strict=True`` a blocking issue raises. With ``strict=False`` the issue
    is reported on the returned object instead, which is what the dashboard wants
    so it can show the user everything wrong at once.
    """
    path = Path(path)
    frame = pd.read_csv(path)
    issues = schema.validate(frame)

    fatal = schema.blocking(issues)
    if fatal and strict:
        summary = "; ".join(f"{i.column}: {i.detail}" for i in fatal)
        raise SchemaError(f"{path.name} does not satisfy the data specification — {summary}")

    prepared = frame if fatal else _prepare(frame)
    return RawFrame(
        frame=prepared,
        source=SourceFile(path=str(path), sha256=_sha256(path), rows=len(prepared)),
        issues=tuple(issues),
    )


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    """Index by date, sort, and drop duplicate dates keeping the last occurrence."""
    prepared = frame.copy()
    prepared[schema.DATE_COLUMN] = pd.to_datetime(prepared[schema.DATE_COLUMN])
    prepared = (
        prepared.sort_values(schema.DATE_COLUMN)
        .drop_duplicates(subset=schema.DATE_COLUMN, keep="last")
        .set_index(schema.DATE_COLUMN)
    )
    prepared.index.name = schema.DATE_COLUMN
    return prepared


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()
