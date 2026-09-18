"""Formatting rules for the model-comparison table.

``ModelRunResult`` is a placeholder input contract pending the team's
run-store design.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from forecasting_engine.validation.crash import CrashDiagnostics
from forecasting_engine.validation.gates import OOS_RANK_IC_GATE, PBO_GATE

MODEL_ORDER: tuple[str, ...] = ("FF5 Benchmark", "Polynomial", "Machine Learning")
"""a missing model still gets a row, showing "Not run" (or "N/A — not
applicable" if the caller names it inapplicable for this target — see
``build_metrics_rows``)."""

NOT_RUN = "Not run"
NOT_APPLICABLE = "N/A — not applicable"
NO_CONFIG_SEARCH = "N/A — no configuration search"

_COLUMNS: tuple[str, ...] = (
    "IC",
    "OOS Rank IC",
    "RMSE",
    "PBO",
    "Crash Recall",
    "Crash Precision",
    "Crash F1",
)


@dataclass(frozen=True)
class Cell:
    """One table cell. ``tone`` is "success"/"danger" only on a gated
    metric; diagnostics and N/A/Not-run cells stay "neutral"."""

    text: str
    tone: str = field(default="neutral")


@dataclass(frozen=True)
class ScreeningSummary:
    """How many walk-forward folds fit each signal, for a run that screened per fold.

    Counts what each fold was actually fit on. A fold whose screening kept no
    signal falls back to fitting on all of them, so it counts towards every
    signal here, and ``fell_back`` says how many folds did that.
    """

    folds: int
    fell_back: int
    counts: tuple[tuple[str, int], ...]
    """``(signal, folds that fit it)``, most-used first. A signal no fold used is
    listed with zero rather than left out — that is what the table exists to show."""


@dataclass(frozen=True)
class FoldTerms:
    """How many of a run's folds ended with any term at all.

    A regularized fit can zero every coefficient on one fold and keep several on
    the next, and a run reports only its most recent fold's equation. Without
    this count that one equation reads as the whole run's answer.
    """

    folds: int
    with_terms: int

    @property
    def every_fold(self) -> bool:
        return self.with_terms == self.folds


@dataclass(frozen=True)
class ModelRunResult:
    """One model family's completed run. ``pbo`` is ``None`` for FF5 (no
    configuration search) — also the signal that row skips the gate badge."""

    ic: float
    oos_rank_ic: float
    rmse: float
    pbo: float | None
    crash: CrashDiagnostics
    screening: ScreeningSummary | None = None
    """Per-fold signal inclusion, or ``None`` for a run that didn't screen (FF5, a
    user-supplied formula): those are handed their features and have nothing to
    filter."""
    terms: FoldTerms | None = None
    """How many folds kept any term. ``None`` only on a result built before this
    field existed (one parked in session state by an older run)."""


def build_metrics_rows(
    results: Mapping[str, ModelRunResult],
    decimals: int = 4,
    *,
    inapplicable: Collection[str] = (),
) -> list[dict[str, Cell]]:
    """One row per name in MODEL_ORDER, always — a model absent from
    ``results`` renders as "Not run", unless it's named in ``inapplicable``
    (e.g. Fama-French for a bond target — it isn't designed to predict bond
    returns even though it would technically run), in which case it renders
    as "N/A — not applicable" instead. A model *with* a result is always
    shown as its result, regardless of ``inapplicable`` — that combination
    shouldn't arise (the page shouldn't offer to run it), but this function
    doesn't second-guess a result it's handed.
    """
    return [
        _row(name, results.get(name), decimals, applicable=name not in inapplicable)
        for name in MODEL_ORDER
    ]


def _row(
    name: str, result: ModelRunResult | None, decimals: int, *, applicable: bool = True
) -> dict[str, Cell]:
    if result is None:
        text = NOT_RUN if applicable else NOT_APPLICABLE
        return {"Model": Cell(name)} | {col: Cell(text) for col in _COLUMNS}

    can_be_gated = result.pbo is not None
    oos_rank_ic_cell = (
        _gated_cell(_fmt(result.oos_rank_ic, decimals), result.oos_rank_ic > OOS_RANK_IC_GATE)
        if can_be_gated
        else Cell(_fmt(result.oos_rank_ic, decimals))
    )
    pbo_cell = (
        Cell(NO_CONFIG_SEARCH)
        if result.pbo is None
        else _gated_cell(_fmt(result.pbo, decimals), result.pbo <= PBO_GATE)
    )

    return {
        "Model": Cell(name),
        "IC": Cell(_fmt(result.ic, decimals)),
        "OOS Rank IC": oos_rank_ic_cell,
        "RMSE": Cell(_fmt(result.rmse, decimals)),
        "PBO": pbo_cell,
        "Crash Recall": Cell(_fmt(result.crash.recall, decimals)),
        "Crash Precision": Cell(_fmt(result.crash.precision, decimals)),
        "Crash F1": Cell(_fmt(result.crash.f1, decimals)),
    }


def _gated_cell(text: str, passed: bool) -> Cell:
    return Cell(text, "success") if passed else Cell(text, "danger")


def _fmt(value: float, decimals: int) -> str:
    return "—" if value != value else f"{value:.{decimals}f}"  # value != value: NaN
