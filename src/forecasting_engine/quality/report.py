"""The shared data quality report.

Four pieces of work write into this model, so it is deliberately open at the
edges rather than shaped around any one of them:

- **Schema validation** contributes blocking faults and range warnings.
- **Outlier detection** contributes informational flags carrying a signal, a
  date and a value, each of which the portfolio manager may include or exclude.
- **Gap checks** contribute genuine gaps, once market holidays are ruled out.
- **The report view** reads all of it: a summary, a per-signal breakdown, and a
  legible "pending" state before any of the checks have run.

Three rules fall out of those requirements and are enforced here.

*Only schema faults block.* Outliers and gaps are informational by design —
flagged values stay in the dataset, and the user proceeds regardless. Severity
is therefore three-way, not a blocking/clean pair.

*Findings have stable ids.* A decision to exclude an outlier has to survive a
re-run and a reworded message, so the id is derived from what the finding is
about — check, signal, dates, rows, value — never from its prose.

*A check that has not run is pending, not absent.* The report always lists every
known check, so the view has something coherent to render before ingestion
finishes.

Nothing here imports Streamlit or pandas; it is plain data.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from forecasting_engine.ingest.provenance import SourceFile


class Severity(StrEnum):
    """How much a finding matters."""

    BLOCKING = "blocking"
    """The file cannot be interpreted. Only schema validation raises these."""

    WARNING = "warning"
    """Worth attention, but the pipeline proceeds."""

    INFO = "info"
    """Observed and recorded. Outliers and gaps live here."""


class CheckStatus(StrEnum):
    """Where a check, or a whole report, has got to."""

    PENDING = "pending"
    PASSED = "passed"
    FLAGGED = "flagged"
    FAILED = "failed"


#: Every check the report knows about, in the order the view shows them. A
#: check absent from a report is rendered pending rather than omitted.
KNOWN_CHECKS: tuple[tuple[str, str], ...] = (
    ("schema", "Schema validation"),
    ("gaps", "Data gaps"),
    ("outliers", "Outliers"),
    ("missing", "Missing values"),
)

DECISIONS: frozenset[str] = frozenset({"undecided", "include", "exclude"})


@dataclass(frozen=True)
class QualityFinding:
    """One thing a check noticed."""

    check: str
    severity: Severity
    detail: str
    signal: str | None = None
    """The column this concerns, or None for a whole-file problem."""

    dates: tuple[str, ...] = ()
    rows: tuple[int, ...] = ()
    """CSV line numbers, as the user's spreadsheet numbers them."""

    value: float | None = None
    count: int = 1
    truncated: bool = False
    """Whether ``rows``/``dates`` list fewer entries than ``count`` found."""

    decision: str = "undecided"
    """The portfolio manager's call: include, exclude, or not yet made."""

    @property
    def id(self) -> str:
        """A stable handle for this finding.

        Derived from what the finding is about, never from ``detail`` — a
        reworded message must not orphan a decision already made against it.
        """
        material = json.dumps(
            [self.check, self.signal, list(self.dates), list(self.rows), self.value],
            sort_keys=True,
        )
        return hashlib.sha256(material.encode()).hexdigest()[:16]

    def decided(self, decision: str) -> QualityFinding:
        """A copy with the user's decision recorded."""
        if decision not in DECISIONS:
            raise ValueError(f"unknown decision {decision!r}; expected one of {sorted(DECISIONS)}")
        return replace(self, decision=decision)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "check": self.check,
            "severity": self.severity.value,
            "detail": self.detail,
            "signal": self.signal,
            "dates": list(self.dates),
            "rows": list(self.rows),
            "value": self.value,
            "count": self.count,
            "truncated": self.truncated,
            "decision": self.decision,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> QualityFinding:
        return cls(
            check=payload["check"],
            severity=Severity(payload["severity"]),
            detail=payload["detail"],
            signal=payload["signal"],
            dates=tuple(payload["dates"]),
            rows=tuple(payload["rows"]),
            value=payload["value"],
            count=payload["count"],
            truncated=payload["truncated"],
            decision=payload["decision"],
        )


@dataclass(frozen=True)
class QualitySection:
    """What one check found."""

    check: str
    title: str
    status: CheckStatus
    findings: tuple[QualityFinding, ...] = ()
    stats: Mapping[str, Any] = field(default_factory=dict)
    """Per-check numbers for the view — thresholds, counts, calendar used."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "title": self.title,
            "status": self.status.value,
            "findings": [f.as_dict() for f in self.findings],
            "stats": dict(self.stats),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> QualitySection:
        return cls(
            check=payload["check"],
            title=payload["title"],
            status=CheckStatus(payload["status"]),
            findings=tuple(QualityFinding.from_dict(f) for f in payload["findings"]),
            stats=dict(payload["stats"]),
        )


@dataclass(frozen=True)
class Coverage:
    """What was ingested: how much, and over what period."""

    rows: int
    columns: int
    start: str | None = None
    end: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"rows": self.rows, "columns": self.columns, "start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Coverage:
        return cls(**payload)


@dataclass(frozen=True)
class QualityReport:
    """Everything known about the quality of one uploaded file."""

    source: SourceFile
    generated_at: datetime
    coverage: Coverage | None = None
    sections: tuple[QualitySection, ...] = ()

    @classmethod
    def pending(cls, source: SourceFile, *, generated_at: datetime | None = None) -> QualityReport:
        """A report for a file whose checks have not run yet.

        Every known check is present and pending, so the view renders something
        coherent instead of a blank page.
        """
        return cls(
            source=source,
            generated_at=generated_at or datetime.now(),
            sections=tuple(
                QualitySection(check=key, title=title, status=CheckStatus.PENDING)
                for key, title in KNOWN_CHECKS
            ),
        )

    def with_section(self, section: QualitySection) -> QualityReport:
        """A copy with ``section`` in place of any earlier one for that check."""
        replaced = False
        sections = []
        for existing in self.sections:
            if existing.check == section.check:
                sections.append(section)
                replaced = True
            else:
                sections.append(existing)
        if not replaced:
            sections.append(section)
        return replace(self, sections=tuple(sections))

    def section(self, check: str) -> QualitySection | None:
        return next((s for s in self.sections if s.check == check), None)

    @property
    def findings(self) -> tuple[QualityFinding, ...]:
        return tuple(f for section in self.sections for f in section.findings)

    @property
    def blocking(self) -> tuple[QualityFinding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.BLOCKING)

    @property
    def excluded(self) -> tuple[QualityFinding, ...]:
        """Findings the portfolio manager chose to drop from the run."""
        return tuple(f for f in self.findings if f.decision == "exclude")

    @property
    def whole_file(self) -> tuple[QualityFinding, ...]:
        """Findings that concern the file rather than any one signal."""
        return tuple(f for f in self.findings if f.signal is None)

    @property
    def passed(self) -> bool:
        """Whether the pipeline may proceed. Only blocking findings stop it."""
        return not self.blocking

    @property
    def status(self) -> CheckStatus:
        if self.blocking:
            return CheckStatus.FAILED
        if self.findings:
            return CheckStatus.FLAGGED
        if any(s.status is CheckStatus.PENDING for s in self.sections):
            return CheckStatus.PENDING
        return CheckStatus.PASSED

    def by_signal(self) -> dict[str, list[QualityFinding]]:
        """Findings grouped by column, across every check.

        This is what the per-signal breakdown expands into: one signal's
        problems gathered from schema, gaps and outliers alike.
        """
        grouped: dict[str, list[QualityFinding]] = {}
        for found in self.findings:
            if found.signal is not None:
                grouped.setdefault(found.signal, []).append(found)
        return grouped

    @property
    def summary(self) -> dict[str, Any]:
        """Headline numbers for the top of the report."""
        by_severity = {severity: 0 for severity in Severity}
        for found in self.findings:
            by_severity[found.severity] += 1
        return {
            "status": self.status.value,
            "passed": self.passed,
            "finding_count": len(self.findings),
            "blocking_count": by_severity[Severity.BLOCKING],
            "warning_count": by_severity[Severity.WARNING],
            "info_count": by_severity[Severity.INFO],
            "pending_count": sum(1 for s in self.sections if s.status is CheckStatus.PENDING),
            "signal_count": len(self.by_signal()),
            "rows": self.coverage.rows if self.coverage else None,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": {
                "name": self.source.name,
                "sha256": self.source.sha256,
                "size_bytes": self.source.size_bytes,
            },
            "generated_at": self.generated_at.isoformat(),
            "coverage": self.coverage.as_dict() if self.coverage else None,
            "sections": [s.as_dict() for s in self.sections],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> QualityReport:
        coverage = payload["coverage"]
        return cls(
            source=SourceFile(**payload["source"]),
            generated_at=datetime.fromisoformat(payload["generated_at"]),
            coverage=Coverage.from_dict(coverage) if coverage else None,
            sections=tuple(QualitySection.from_dict(s) for s in payload["sections"]),
        )
