# Signal Screening — Design

**Date:** 2026-09-12
**Status:** Approved
**Tickets:** FYP-102 – FYP-110
**Related:** `2026-07-29-forecasting-engine-architecture-design.md` (stage 3→4 seam, `FeaturePanel`, `PurgedWalkForward`)

## 1. Problem

The screening tickets (per-signal IC, inclusion threshold, exclusion, signal registry,
auto-trigger, walk-forward re-screening) assume a lagged `FeaturePanel` and a
`PurgedWalkForward` walk-forward loop. Neither exists in the repo yet — only
`ingest/`, `quality/`, `store/`, `extraction/` are built (Sprint 1's align/lag step and
Sprint 2's splitter, per the architecture doc's roadmap, haven't landed). This spec
covers building the minimum of both, plus the screening module itself.

## 2. Scope

**In scope**

1. `FeaturePanel` + `align_and_lag()` — enough of the stage-3 output to give screening
   something real to run against.
2. `PurgedWalkForward` — enough of the walk-forward splitter to re-evaluate screening
   at each rebalance step using only trailing data.
3. `rank_ic()` — the one metric screening needs.
4. Signal screening itself: per-signal IC, documented inclusion threshold, exclusion
   logic, a registry that never drops a signal from view, auto-run after Module 1,
   re-evaluation per walk-forward fold.
5. A Streamlit page rendering the registry.
6. Unit + integration tests.

**Out of scope** (no consumer exists yet; adding now is speculative)

- `RunConfig` / `ModelSpec` / `PortfolioSpec` / `DataSpec` config plumbing.
- `CPCV` (combinatorial purged CV) — doc marks it "where feasible", plain
  `PurgedWalkForward` covers the walk-forward requirement.
- `PBO`, `DSR`, `RMSE`, crash recall — Sprint 3 metrics, not needed to screen a signal.
- `Provenance` wired into `FeaturePanel` — only `SourceFile` exists today with no
  aggregate `Provenance` type to compose; adding one is a separate piece of work.

## 3. Components

### 3.1 `src/forecasting_engine/ingest/align.py` (new)

```python
@dataclass(frozen=True)
class FeaturePanel:
    frame: pd.DataFrame        # DatetimeIndex; lagged signals + one forward-return target
    signals: tuple[str, ...]
    targets: tuple[str, ...]
    lag_days: int

def align_and_lag(
    frame: pd.DataFrame,
    signal_cols: Sequence[str],
    price_col: str,
    horizon: int = 5,
    lag_days: int = 1,
) -> FeaturePanel: ...
```

- Every signal column is shifted forward `lag_days` (default 1) so it is dated to when
  it was observable — the one shift rule from the architecture doc.
- Target is a forward return derived from `price_col`:
  `frame[price_col].pct_change(horizon).shift(-horizon)`, named `fwd_return_{horizon}d`.
- `__post_init__` asserts `lag_days >= 1` and that no target column appears in `signals`
  (mirrors the frozen-contract rule already decided for `FeaturePanel`).
- Input is whatever `quality.build.apply_decisions()` already returns — no new
  ingestion path.

### 3.2 `src/forecasting_engine/validation/splitters.py` (new)

```python
class PurgedWalkForward:
    def __init__(self, train: int, test: int, embargo: int): ...
    def split(self, panel: FeaturePanel) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
        """Rolling (train_idx, test_idx) folds: train, embargo gap, test, roll forward."""
```

Rolls forward over `panel.frame.index` in fixed-size windows; the embargo gap between
train and test is dropped from both. This is the "only splitter in the codebase" the
architecture doc specifies — CPCV is explicitly deferred.

### 3.3 `src/forecasting_engine/validation/metrics.py` (new)

```python
def rank_ic(signal: pd.Series, target: pd.Series) -> float:
    """Spearman rank correlation, NaNs dropped pairwise. NaN if fewer than 2 pairs remain."""
```

Uses `pandas.Series.corr(method="spearman")` — no new dependency.

### 3.4 `src/forecasting_engine/features/screening.py` (new)

```python
INCLUSION_THRESHOLD: float = 0.02
"""Working default (documented, not sponsor-confirmed): minimum |rank IC| for a
signal to be included in modelling. Revisit once Alpha Norm gives a number."""

@dataclass(frozen=True)
class SignalScore:
    signal: str
    ic: float
    included: bool

def screen_signals(
    panel: FeaturePanel, threshold: float = INCLUSION_THRESHOLD
) -> tuple[SignalScore, ...]:
    """One IC score per signal in panel.signals, against panel.targets[0]. Every
    signal is scored and returned — inclusion never removes it from the tuple."""

def screen_over_folds(
    panel: FeaturePanel, folds: Iterable[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]
) -> dict[int, tuple[SignalScore, ...]]:
    """screen_signals() re-run per fold using only that fold's train_idx slice of
    panel.frame — never the test window, so inclusion never uses future data."""

def run_screening(
    frame: pd.DataFrame, signal_cols: Sequence[str], price_col: str
) -> tuple[SignalScore, ...]:
    """align_and_lag() -> screen_signals(), chained. 'Automatic' means this is the
    next call after Module 1's apply_decisions() output is ready, not a new event
    system."""
```

### 3.5 `app/pages/2_Signals.py` (new)

Renders `screen_signals()` output as a table: signal, IC, included (✅/❌). No maths in
the page — it calls into `features.screening` and displays the tuple, following the
`1_Data.py` pattern of a thin page over a src-side report object.

## 4. Data flow

```
apply_decisions(frame, report)   # existing, quality/build.py
        │
        ▼
align_and_lag(frame, signals, price_col)   # new: ingest/align.py
        │
        ▼
FeaturePanel
        │
        ├── screen_signals(panel)                         → registry (whole-sample)
        │
        └── PurgedWalkForward(...).split(panel)
                    │
                    ▼
            screen_over_folds(panel, folds)                → registry per rebalance step
```

## 5. Testing

- `tests/unit/test_align.py` — lag applied correctly; target column excluded from
  `signals`; `lag_days < 1` raises.
- `tests/unit/test_splitters.py` — fold boundaries, embargo gap excluded from both
  sides, folds roll forward and stop at the frame's end.
- `tests/unit/test_metrics.py` — `rank_ic` against hand-computed values on a small
  frame; NaN handling.
- `tests/unit/test_screening.py` — synthetic panel with one strongly-correlated and
  one random signal: strong included, weak excluded (FYP-109).
- `tests/integration/test_screening_flow.py` — full chain, `apply_decisions` fixture →
  `align_and_lag` → `PurgedWalkForward` → `screen_over_folds`; asserts a fold's
  inclusion decision only reflects data at or before that fold's train window end
  (FYP-108, FYP-110).

## 6. Open question carried forward

`INCLUSION_THRESHOLD = 0.02` is a working default, not a sponsor-confirmed number —
same treatment as the architecture doc's other working assumptions (§11). Documented
in the module docstring; revisit when Alpha Norm gives a figure.
