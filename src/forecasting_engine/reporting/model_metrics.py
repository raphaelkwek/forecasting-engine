"""Formatting rules for the model-comparison table.

``ModelRunResult`` is a placeholder input contract pending the team's
run-store design.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from forecasting_engine.validation.crash import CrashDiagnostics
from forecasting_engine.validation.gates import OOS_RANK_IC_GATE, PBO_GATE

MODEL_ORDER: tuple[str, ...] = ("FF5 Benchmark", "Polynomial", "Machine Learning")
"""a missing model still gets a row, showing "Not run"."""

NOT_RUN = "Not run"
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


def build_metrics_rows(
    results: Mapping[str, ModelRunResult], decimals: int = 4
) -> list[dict[str, Cell]]:
    """One row per name in MODEL_ORDER, always — a model absent from
    ``results`` renders as "Not run" rather than being omitted."""
    return [_row(name, results.get(name), decimals) for name in MODEL_ORDER]


def _row(name: str, result: ModelRunResult | None, decimals: int) -> dict[str, Cell]:
    if result is None:
        return {"Model": Cell(name)} | {col: Cell(NOT_RUN) for col in _COLUMNS}

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
