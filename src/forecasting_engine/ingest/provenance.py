"""Where a dataset came from.

Every artefact the engine produces can be traced back to a ``SourceFile``. The
content hash — not the filename — is the identity: two uploads of the same
bytes are the same source however they were named.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceFile:
    """One input file, identified by the hash of its contents."""

    name: str
    sha256: str
    size_bytes: int
    path: Path | None = None
    """Where the bytes were stored, or ``None`` if they were never persisted."""

    @property
    def short_hash(self) -> str:
        """The first 12 hex characters — enough to recognise, short enough to show."""
        return self.sha256[:12]

    @classmethod
    def of(cls, name: str, data: bytes, path: Path | None = None) -> SourceFile:
        return cls(
            name=name,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            path=path,
        )
