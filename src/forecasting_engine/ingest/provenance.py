"""Records of where data came from, carried through the whole pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFile:
    """One input file, identified by content rather than by name."""

    path: str
    sha256: str
    rows: int


@dataclass(frozen=True)
class Provenance:
    """Everything needed to say where a FeaturePanel came from."""

    sources: tuple[SourceFile, ...]
    built_at: str
    horizon_days: int
