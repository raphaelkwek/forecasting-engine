"""End-to-end: quality decisions -> lag-safe panel -> walk-forward registry."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from forecasting_engine.features.screening import screen_over_folds, screen_signals
from forecasting_engine.ingest.align import align_and_lag
from forecasting_engine.ingest.provenance import SourceFile
from forecasting_engine.quality.build import apply_decisions
from forecasting_engine.quality.report import QualityReport
from forecasting_engine.validation.metrics import rank_ic
from forecasting_engine.validation.splitters import PurgedWalkForward


def _raw_frame(n: int = 80) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    price = 100 + np.cumsum(rng.normal(scale=0.5, size=n))
    strong_signal = np.roll(price, -1) - price
    return pd.DataFrame({"strong_signal": strong_signal, "price": price}, index=idx)


def _empty_quality_report() -> QualityReport:
    return QualityReport(
        source=SourceFile.of("prices.csv", b"irrelevant"),
        generated_at=datetime.now(),
    )


def test_screening_flow_from_quality_decisions_to_walk_forward_registry():
    frame = _raw_frame()
    report = _empty_quality_report()

    decided = apply_decisions(frame, report)
    panel = align_and_lag(decided, ["strong_signal"], "price", horizon=1, lag_days=1)

    folds = list(PurgedWalkForward(train=30, test=5, embargo=1).split(panel))
    assert folds, "fixture must be large enough to produce at least one fold"

    per_fold = screen_over_folds(panel, folds)

    for fold_index, (train_idx, _test_idx) in enumerate(folds):
        train_slice = panel.frame.loc[train_idx]
        expected_ic = rank_ic(train_slice["strong_signal"], train_slice[panel.targets[0]])
        actual_ic = next(s.ic for s in per_fold[fold_index] if s.signal == "strong_signal")
        assert actual_ic == expected_ic or (pd.isna(actual_ic) and pd.isna(expected_ic))


def test_whole_sample_screening_also_registers_every_signal():
    frame = _raw_frame()
    panel = align_and_lag(frame, ["strong_signal"], "price", horizon=1, lag_days=1)
    scores = screen_signals(panel)
    assert {s.signal for s in scores} == {"strong_signal"}
