"""File-level validation of an uploaded CSV.

This is the gate between a browser upload and the rest of the engine. It
answers one question — is this a file we can work with at all? — and answers it
in three parts: the right extension, within the size limit, and parseable as
delimited text.

It deliberately says nothing about *columns*. Whether the file carries the
signals the contract requires is schema validation's job (FYP-8), which runs on
the frame this module returns. Keeping the two apart means a portfolio manager
who uploads a holiday photo gets "that is not a CSV" rather than a list of
eight missing columns.

Nothing here imports Streamlit; the dashboard is a caller, not a dependency.
See ``docs/data-specification.md`` for the contract these rules enforce.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pandas as pd

from forecasting_engine.ingest.provenance import SourceFile

#: Maximum accepted upload. Roughly six times the largest file the data
#: specification can plausibly produce — see the "File size" section there
#: before changing it, and change it in both places.
MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024

#: Where accepted uploads are stored, keyed by content hash. Gitignored.
DEFAULT_UPLOADS_DIR: Path = Path("data/uploads")

DATE_COLUMN = "date"

_EXPORT_HINT = "Re-export it using Save As → CSV UTF-8."


class UploadError(Exception):
    """An upload we are refusing.

    ``message`` is written for a portfolio manager and is safe to render
    directly in the dashboard.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class FileTypeError(UploadError):
    """The file is not a CSV."""


class FileSizeError(UploadError):
    """The file is larger than the documented limit."""


class CsvParseError(UploadError):
    """The file ends in .csv but its contents are not delimited text."""


@dataclass(frozen=True)
class AcceptedUpload:
    """A file that passed every file-level check."""

    frame: pd.DataFrame
    source: SourceFile

    @property
    def row_count(self) -> int:
        return len(self.frame)


def check_extension(filename: str) -> None:
    """Raise ``FileTypeError`` unless ``filename`` ends in .csv."""
    suffix = Path(filename).suffix
    if suffix.lower() == ".csv":
        return
    got = f"a {suffix} file" if suffix else "a file with no extension"
    raise FileTypeError(f"Only .csv files are accepted. {filename!r} is {got}. {_EXPORT_HINT}")


def check_size(size_bytes: int, *, filename: str) -> None:
    """Raise ``FileSizeError`` if ``size_bytes`` exceeds the documented limit."""
    if size_bytes <= MAX_UPLOAD_BYTES:
        return

    got, limit = _megabytes(size_bytes), _megabytes(MAX_UPLOAD_BYTES)
    if got == limit:
        # Barely over. Rounded megabytes would read "25.0 MB is over the
        # 25.0 MB limit", so be exact instead of merely consistent.
        raise FileSizeError(
            f"{filename!r} is {size_bytes:,} bytes, just over the "
            f"{limit} limit of {MAX_UPLOAD_BYTES:,} bytes."
        )
    raise FileSizeError(f"{filename!r} is {got}, which is over the {limit} limit.")


def parse_csv(data: bytes) -> pd.DataFrame:
    """Parse ``data`` as a UTF-8 CSV, or raise ``CsvParseError``."""
    try:
        return pd.read_csv(BytesIO(data), encoding="utf-8")
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise CsvParseError(
            f"The file could not be read as a CSV ({type(exc).__name__}). "
            f"Renaming a file does not change its format. {_EXPORT_HINT}"
        ) from exc


def accept_upload(
    filename: str,
    data: bytes,
    *,
    uploads_dir: Path | None = DEFAULT_UPLOADS_DIR,
) -> AcceptedUpload:
    """Validate an upload and, unless ``uploads_dir`` is None, persist it.

    Checks run cheapest-first, so an oversized file is refused before we spend
    anything trying to parse it. Accepted bytes are written to
    ``uploads_dir/<sha256>.csv``; an identical re-upload resolves to the same
    path and is not rewritten.
    """
    check_extension(filename)
    check_size(len(data), filename=filename)
    frame = parse_csv(data)

    source = SourceFile.of(filename, data)
    if uploads_dir is None:
        return AcceptedUpload(frame=frame, source=source)

    uploads_dir.mkdir(parents=True, exist_ok=True)
    path = uploads_dir / f"{source.sha256}.csv"
    if not path.exists():
        path.write_bytes(data)

    return AcceptedUpload(frame=frame, source=SourceFile.of(filename, data, path=path))


def date_range(frame: pd.DataFrame) -> tuple[str, str] | None:
    """First and last date as ISO strings, or None if they cannot be read.

    Best effort, for the upload confirmation message only. A file with no
    usable date column is still a valid *file*; it is schema validation that
    decides whether it is a valid dataset.
    """
    if DATE_COLUMN not in frame.columns:
        return None
    dates = pd.to_datetime(frame[DATE_COLUMN], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.min().date().isoformat(), dates.max().date().isoformat()


def _megabytes(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.1f} MB"
