# Signal Screening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Screen every ingested signal for standalone predictive power (rank IC against
a forward return), exclude signals below a documented threshold from modelling while
keeping them visible in a registry, and re-run that screen at each walk-forward
rebalance step using only trailing data.

**Architecture:** Build the minimum missing foundation first — a lag-safe
`FeaturePanel` (`ingest/align.py`) and a `PurgedWalkForward` splitter
(`validation/splitters.py`) — then layer univariate IC screening
(`features/screening.py`) on top, and expose it as a Streamlit page reading the
existing Bloomberg-merge session state.

**Tech Stack:** Python, pandas (Spearman correlation via `Series.corr`), pytest,
Streamlit. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-signal-screening-design.md`

## Global Constraints

- `lag_days >= 1` always; no fitting/screening function may accept an unlagged frame.
- `PurgedWalkForward` is the only splitter — no CPCV in this plan.
- `INCLUSION_THRESHOLD` is a documented working default (`0.02`), not sponsor-confirmed.
- No new dependencies; Spearman IC uses `pandas.Series.corr(method="spearman")`.
- Line length 100, ruff rules `E, F, I, UP, B` (existing `pyproject.toml`) — run
  `uv run ruff check .` before each commit.
- A signal is never dropped from a screening result — `screen_signals` /
  `screen_over_folds` always return every signal, `included` flag or not.

---

### Task 1: `FeaturePanel` + `align_and_lag()`

**Files:**
- Create: `src/forecasting_engine/ingest/align.py`
- Test: `tests/unit/test_align.py`

**Interfaces:**
- Produces: `FeaturePanel(frame: pd.DataFrame, signals: tuple[str, ...], targets: tuple[str, ...], lag_days: int)`
  (frozen dataclass), `align_and_lag(frame: pd.DataFrame, signal_cols: Sequence[str], price_col: str, horizon: int = 5, lag_days: int = 1) -> FeaturePanel`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_align.py
import pandas as pd
import pytest

from forecasting_engine.ingest.align import FeaturePanel, align_and_lag


def _frame() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    return pd.DataFrame(
        {"signal_a": range(10), "price": [100 + i for i in range(10)]},
        index=idx,
    )


def test_align_and_lag_shifts_signals_forward():
    panel = align_and_lag(_frame(), ["signal_a"], "price", horizon=2, lag_days=1)
    assert panel.frame["signal_a"].iloc[2] == 1
    assert pd.isna(panel.frame["signal_a"].iloc[0])


def test_align_and_lag_computes_forward_return_target():
    panel = align_and_lag(_frame(), ["signal_a"], "price", horizon=2, lag_days=1)
    assert panel.targets == ("fwd_return_2d",)
    expected = (102 / 100) - 1
    assert panel.frame["fwd_return_2d"].iloc[0] == pytest.approx(expected)
    assert pd.isna(panel.frame["fwd_return_2d"].iloc[-1])


def test_lag_days_must_be_positive():
    with pytest.raises(ValueError):
        align_and_lag(_frame(), ["signal_a"], "price", lag_days=0)


def test_target_cannot_also_be_a_signal():
    with pytest.raises(ValueError):
        FeaturePanel(
            frame=_frame(),
            signals=("fwd_return_2d",),
            targets=("fwd_return_2d",),
            lag_days=1,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_align.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forecasting_engine.ingest.align'`

- [ ] **Step 3: Write the implementation**

```python
# src/forecasting_engine/ingest/align.py
"""FeaturePanel: the lag-safe dataset screening and modelling consume.

Built by align_and_lag() from whatever quality.build.apply_decisions() (or,
today, the Bloomberg merge) produced. No screening or fitting function
accepts a bare DataFrame, so there is no type-legal way to run on unlagged
data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FeaturePanel:
    """A dataset where every signal is dated to when it was observable."""

    frame: pd.DataFrame
    signals: tuple[str, ...]
    targets: tuple[str, ...]
    lag_days: int

    def __post_init__(self) -> None:
        if self.lag_days < 1:
            raise ValueError(f"lag_days must be >= 1, got {self.lag_days}")
        overlap = set(self.signals) & set(self.targets)
        if overlap:
            raise ValueError(f"target column(s) {overlap} also listed as signals")


def align_and_lag(
    frame: pd.DataFrame,
    signal_cols: Sequence[str],
    price_col: str,
    horizon: int = 5,
    lag_days: int = 1,
) -> FeaturePanel:
    """Lag every signal, derive a forward-return target, freeze both into a FeaturePanel.

    ``price_col`` is a price/level column already present in ``frame``; the
    target is the ``horizon``-day forward return computed from it. Every
    signal in ``signal_cols`` is shifted forward ``lag_days`` so its value on
    a given date is what was actually observable on that date.
    """
    target_col = f"fwd_return_{horizon}d"
    out = frame.copy()
    out[target_col] = out[price_col].pct_change(horizon).shift(-horizon)
    out[list(signal_cols)] = out[list(signal_cols)].shift(lag_days)
    return FeaturePanel(
        frame=out,
        signals=tuple(signal_cols),
        targets=(target_col,),
        lag_days=lag_days,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_align.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/forecasting_engine/ingest/align.py tests/unit/test_align.py
git commit -m "feat: add FeaturePanel and align_and_lag"
```

---

### Task 2: `PurgedWalkForward` splitter

**Files:**
- Create: `src/forecasting_engine/validation/__init__.py`
- Create: `src/forecasting_engine/validation/splitters.py`
- Test: `tests/unit/test_splitters.py`

**Interfaces:**
- Consumes: `FeaturePanel` from Task 1 (`forecasting_engine.ingest.align`).
- Produces: `PurgedWalkForward(train: int, test: int, embargo: int)` with
  `.split(panel: FeaturePanel) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_splitters.py
import pandas as pd

from forecasting_engine.ingest.align import FeaturePanel
from forecasting_engine.validation.splitters import PurgedWalkForward


def _panel(n: int) -> FeaturePanel:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    frame = pd.DataFrame({"signal_a": range(n), "fwd_return_1d": range(n)}, index=idx)
    return FeaturePanel(
        frame=frame, signals=("signal_a",), targets=("fwd_return_1d",), lag_days=1
    )


def test_split_yields_expected_fold_sizes():
    panel = _panel(20)
    folds = list(PurgedWalkForward(train=10, test=3, embargo=2).split(panel))
    assert len(folds[0][0]) == 10
    assert len(folds[0][1]) == 3


def test_embargo_gap_excluded_from_both_sides():
    panel = _panel(20)
    train_idx, test_idx = next(PurgedWalkForward(train=10, test=3, embargo=2).split(panel))
    gap = panel.frame.index[10:12]
    assert not gap.isin(train_idx).any()
    assert not gap.isin(test_idx).any()


def test_folds_roll_forward():
    panel = _panel(20)
    folds = list(PurgedWalkForward(train=10, test=3, embargo=2).split(panel))
    assert len(folds) == 2
    assert folds[1][0][0] == panel.frame.index[3]


def test_stops_when_not_enough_data_left():
    panel = _panel(15)
    folds = list(PurgedWalkForward(train=10, test=3, embargo=2).split(panel))
    assert len(folds) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_splitters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forecasting_engine.validation'`

- [ ] **Step 3: Write the implementation**

```python
# src/forecasting_engine/validation/__init__.py
"""Out-of-sample validation: the walk-forward splitter and its metrics."""
```

```python
# src/forecasting_engine/validation/splitters.py
"""PurgedWalkForward: the only splitter in the codebase.

Rolls a fixed-size train/test window forward across a FeaturePanel's index,
dropping an embargo gap between train and test so overlapping forward-return
labels can't leak across the split.
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd

from forecasting_engine.ingest.align import FeaturePanel


class PurgedWalkForward:
    def __init__(self, train: int, test: int, embargo: int):
        self.train = train
        self.test = test
        self.embargo = embargo

    def split(
        self, panel: FeaturePanel
    ) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
        index = panel.frame.index
        start = 0
        while start + self.train + self.embargo + self.test <= len(index):
            train_idx = index[start : start + self.train]
            test_start = start + self.train + self.embargo
            test_idx = index[test_start : test_start + self.test]
            yield train_idx, test_idx
            start += self.test
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_splitters.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/forecasting_engine/validation/__init__.py src/forecasting_engine/validation/splitters.py tests/unit/test_splitters.py
git commit -m "feat: add PurgedWalkForward splitter"
```

---

### Task 3: `rank_ic()` metric

**Files:**
- Create: `src/forecasting_engine/validation/metrics.py`
- Test: `tests/unit/test_metrics.py`

**Interfaces:**
- Produces: `rank_ic(signal: pd.Series, target: pd.Series) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_metrics.py
import numpy as np
import pandas as pd

from forecasting_engine.validation.metrics import rank_ic


def test_rank_ic_perfect_positive_correlation():
    signal = pd.Series([1, 2, 3, 4, 5])
    target = pd.Series([10, 20, 30, 40, 50])
    assert rank_ic(signal, target) == 1.0


def test_rank_ic_perfect_negative_correlation():
    signal = pd.Series([1, 2, 3, 4, 5])
    target = pd.Series([50, 40, 30, 20, 10])
    assert rank_ic(signal, target) == -1.0


def test_rank_ic_drops_nan_pairs():
    signal = pd.Series([1, 2, np.nan, 4, 5])
    target = pd.Series([10, 20, 30, np.nan, 50])
    assert rank_ic(signal, target) == 1.0


def test_rank_ic_nan_when_fewer_than_two_pairs():
    signal = pd.Series([1, np.nan])
    target = pd.Series([np.nan, 20])
    assert np.isnan(rank_ic(signal, target))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forecasting_engine.validation.metrics'`

- [ ] **Step 3: Write the implementation**

```python
# src/forecasting_engine/validation/metrics.py
"""Prediction-quality metrics shared across screening and validation."""

from __future__ import annotations

import pandas as pd


def rank_ic(signal: pd.Series, target: pd.Series) -> float:
    """Spearman rank correlation between a signal and its target.

    Pairs with a NaN in either series are dropped before scoring. Returns NaN
    if fewer than two valid pairs remain.
    """
    paired = pd.concat([signal, target], axis=1).dropna()
    if len(paired) < 2:
        return float("nan")
    return paired.iloc[:, 0].corr(paired.iloc[:, 1], method="spearman")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_metrics.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/forecasting_engine/validation/metrics.py tests/unit/test_metrics.py
git commit -m "feat: add rank_ic metric"
```

---

### Task 4: Screening (`features/screening.py`)

**Files:**
- Create: `src/forecasting_engine/features/__init__.py`
- Create: `src/forecasting_engine/features/screening.py`
- Test: `tests/unit/test_screening.py`

**Interfaces:**
- Consumes: `FeaturePanel`, `align_and_lag` (Task 1); `rank_ic` (Task 3);
  `PurgedWalkForward` fold type `Iterable[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]` (Task 2, used only in tests here).
- Produces: `INCLUSION_THRESHOLD: float`, `SignalScore(signal: str, ic: float, included: bool)`,
  `screen_signals(panel, threshold=INCLUSION_THRESHOLD) -> tuple[SignalScore, ...]`,
  `screen_over_folds(panel, folds, threshold=INCLUSION_THRESHOLD) -> dict[int, tuple[SignalScore, ...]]`,
  `run_screening(frame, signal_cols, price_col, threshold=INCLUSION_THRESHOLD) -> tuple[SignalScore, ...]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_screening.py
import numpy as np
import pandas as pd

from forecasting_engine.features.screening import screen_over_folds, screen_signals
from forecasting_engine.ingest.align import FeaturePanel
from forecasting_engine.validation.splitters import PurgedWalkForward


def _panel_with_known_signals(n: int = 60) -> FeaturePanel:
    rng = np.random.default_rng(0)
    target = rng.normal(size=n)
    strong = target * 2 + rng.normal(scale=0.01, size=n)
    weak = rng.normal(size=n)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    frame = pd.DataFrame(
        {"strong_signal": strong, "weak_signal": weak, "fwd_return_1d": target},
        index=idx,
    )
    return FeaturePanel(
        frame=frame,
        signals=("strong_signal", "weak_signal"),
        targets=("fwd_return_1d",),
        lag_days=1,
    )


def test_strong_signal_included_weak_signal_excluded():
    scores = {s.signal: s for s in screen_signals(_panel_with_known_signals())}
    assert scores["strong_signal"].included is True
    assert scores["weak_signal"].included is False


def test_every_signal_scored_even_when_excluded():
    scores = screen_signals(_panel_with_known_signals())
    assert {s.signal for s in scores} == {"strong_signal", "weak_signal"}


def test_screen_over_folds_uses_only_trailing_window():
    panel = _panel_with_known_signals()
    folds = list(PurgedWalkForward(train=30, test=5, embargo=2).split(panel))
    results = screen_over_folds(panel, folds)
    assert len(results) == len(folds)
    for fold_scores in results.values():
        assert {s.signal for s in fold_scores} == {"strong_signal", "weak_signal"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_screening.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forecasting_engine.features'`

- [ ] **Step 3: Write the implementation**

```python
# src/forecasting_engine/features/__init__.py
"""Feature screening: which signals carry enough standalone predictive power."""
```

```python
# src/forecasting_engine/features/screening.py
"""Univariate IC screening: which signals carry enough standalone predictive
power to be worth modelling.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import pandas as pd

from forecasting_engine.ingest.align import FeaturePanel, align_and_lag
from forecasting_engine.validation.metrics import rank_ic

INCLUSION_THRESHOLD: float = 0.02
"""Working default (not sponsor-confirmed): minimum absolute rank IC for a
signal to be included in modelling. Revisit once Alpha Norm gives a number."""


@dataclass(frozen=True)
class SignalScore:
    """One signal's screening result. Always produced, even when excluded."""

    signal: str
    ic: float
    included: bool


def screen_signals(
    panel: FeaturePanel, threshold: float = INCLUSION_THRESHOLD
) -> tuple[SignalScore, ...]:
    """Score every signal in ``panel`` against its target; never drop one."""
    target = panel.frame[panel.targets[0]]
    scores = []
    for name in panel.signals:
        ic = rank_ic(panel.frame[name], target)
        included = not pd.isna(ic) and abs(ic) >= threshold
        scores.append(SignalScore(signal=name, ic=ic, included=included))
    return tuple(scores)


def screen_over_folds(
    panel: FeaturePanel,
    folds: Iterable[tuple[pd.DatetimeIndex, pd.DatetimeIndex]],
    threshold: float = INCLUSION_THRESHOLD,
) -> dict[int, tuple[SignalScore, ...]]:
    """Re-run screen_signals() per fold, using only that fold's train window."""
    results = {}
    for fold_index, (train_idx, _test_idx) in enumerate(folds):
        train_panel = FeaturePanel(
            frame=panel.frame.loc[train_idx],
            signals=panel.signals,
            targets=panel.targets,
            lag_days=panel.lag_days,
        )
        results[fold_index] = screen_signals(train_panel, threshold=threshold)
    return results


def run_screening(
    frame: pd.DataFrame,
    signal_cols: Sequence[str],
    price_col: str,
    threshold: float = INCLUSION_THRESHOLD,
) -> tuple[SignalScore, ...]:
    """align_and_lag() then screen_signals() — the call to make once Module 1's
    quality decisions are applied and a screening pass is wanted."""
    panel = align_and_lag(frame, signal_cols, price_col)
    return screen_signals(panel, threshold=threshold)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_screening.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/forecasting_engine/features/__init__.py src/forecasting_engine/features/screening.py tests/unit/test_screening.py
git commit -m "feat: add signal screening (IC score, inclusion threshold, walk-forward re-screening)"
```

---

### Task 5: Streamlit registry page + integration test

**Files:**
- Create: `app/pages/2_Signals.py`
- Create: `tests/integration/test_screening_flow.py`

**Interfaces:**
- Consumes: `run_screening`, `screen_signals`, `screen_over_folds` (Task 4);
  `align_and_lag` (Task 1); `PurgedWalkForward` (Task 2); `rank_ic` (Task 3);
  `bloomberg_extraction_panel.MERGED_KEY` (existing, `app/bloomberg_extraction_panel.py:32`);
  `bloomberg_csv.DATE_COLUMN` (existing, `src/forecasting_engine/extraction/bloomberg_csv.py:26`);
  `quality.build.apply_decisions`, `quality.report.QualityReport` (existing).

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_screening_flow.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_screening_flow.py -v`
Expected: FAIL if any Task 1–4 piece is missing; once Tasks 1–4 are done this should
already pass — this test exercises no new production code, only the wiring between
existing pieces, so treat a failure here as a signal that an earlier task's contract
doesn't match this plan and needs fixing before continuing.

- [ ] **Step 3: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_screening_flow.py -v`
Expected: PASS (2 tests)

- [ ] **Step 4: Write the Streamlit page**

```python
# app/pages/2_Signals.py
"""Signals page: per-signal IC screening and the inclusion registry.

Reads the already-merged frame from the Data page's session state; no maths
lives here — screening logic is in forecasting_engine.features.screening.
"""

from __future__ import annotations

import streamlit as st

import bloomberg_extraction_panel
from forecasting_engine.extraction.bloomberg_csv import DATE_COLUMN
from forecasting_engine.features.screening import run_screening

st.set_page_config(page_title="Signals · Forecasting Engine", page_icon=":material/query_stats:")

st.header("Signal screening")
st.caption(
    "Each ingested signal is scored by its rank IC against the forward return. "
    "Signals below the inclusion threshold stay visible here, excluded from modelling."
)

merged = st.session_state.get(bloomberg_extraction_panel.MERGED_KEY)
if merged is None:
    st.info("Upload data on the Data page first.")
else:
    numeric_cols = [
        c for c in merged.columns if c != DATE_COLUMN and merged[c].dtype.kind in "fi"
    ]
    price_col = st.selectbox("Target price/level column", numeric_cols)
    signal_cols = [c for c in numeric_cols if c != price_col]
    if price_col and signal_cols:
        indexed = merged.set_index(DATE_COLUMN)
        scores = run_screening(indexed, signal_cols, price_col)
        st.dataframe(
            [
                {
                    "Signal": s.signal,
                    "IC": round(s.ic, 4) if s.ic == s.ic else None,
                    "Included": "Yes" if s.included else "No",
                }
                for s in scores
            ],
            width="stretch",
        )
```

- [ ] **Step 5: Manual check**

Run: `uv run streamlit run app/Home.py`, open the Data page, upload a Bloomberg CSV
export, then open the Signals page and confirm the table renders with an IC and an
Included column for every signal (never fewer rows than uploaded signal columns).

- [ ] **Step 6: Commit**

```bash
git add app/pages/2_Signals.py tests/integration/test_screening_flow.py
git commit -m "feat: add signal registry page and end-to-end screening test"
```

---

### Task 6: Completeness and cleanliness review

This task has no code steps of its own — it is a review pass over Tasks 1–5's diff,
run after they are committed.

**Do this:**

1. Re-read `docs/superpowers/specs/2026-09-12-signal-screening-design.md` and the
   original acceptance criteria (FYP-102 – FYP-110) and check each one against the
   actual code:
   - FYP-102 (IC per signal, T-1 lag): `align_and_lag` lags signals by `lag_days=1`
     default; `screen_signals` scores every entry in `panel.signals`.
   - FYP-103 (documented threshold): `INCLUSION_THRESHOLD` docstring in `screening.py`.
   - FYP-104 (auto-exclude below threshold): `included` flag in `SignalScore`.
   - FYP-105/106 (registry, excluded stay visible): `screen_signals` always returns
     one `SignalScore` per signal, included or not — grep the diff for any `filter`,
     `drop`, or list-comprehension `if` that would silently shrink the tuple.
   - FYP-107 (auto-trigger after Module 1): `run_screening` chains
     `align_and_lag → screen_signals`; confirm nothing needs a manual second step in
     `app/pages/2_Signals.py`.
   - FYP-108 (re-screen per rebalance step, trailing data only): `screen_over_folds`
     slices `panel.frame` to `train_idx` before scoring — confirm no path in that
     function reads `panel.frame` unsliced.
   - FYP-109 (unit tests, known strong/weak signals): `tests/unit/test_screening.py`.
   - FYP-110 (integration, screening feeds model fitting): `tests/integration/test_screening_flow.py`
     chains `apply_decisions → align_and_lag → PurgedWalkForward → screen_over_folds`.
2. Run `uv run ruff check .` and `uv run pytest` from the repo root; both must pass
   clean.
3. Look for redundancy against **existing** code, not just internal duplication:
   is there already a lag/shift helper elsewhere in `ingest/` or `quality/` that
   `align_and_lag` should have reused instead of writing its own `.shift(...)`? Is
   there an existing correlation helper anywhere in the repo `rank_ic` duplicates?
   (There should not be — this was checked during design — but re-verify against the
   current `main`/branch state, since other in-flight work may have landed since.)
4. Look for anything added beyond what the tickets ask for: no `RunConfig`/`ModelSpec`
   plumbing, no CPCV, no PBO/DSR/RMSE/crash-recall metrics, no `Provenance` field
   added to `FeaturePanel`. If any of Tasks 1–5 introduced one of these, cut it.
5. Check every new public function/class has exactly the signature this plan
   specified (drift here breaks the next module that imports it).
6. Fix anything found directly (small, in-place edits), re-run
   `uv run ruff check .` and `uv run pytest`, then commit:

```bash
git add -A
git commit -m "chore: review pass on signal screening — cleanup and verification"
```

If nothing needed fixing, skip the commit and report that the review found the
implementation already clean.
