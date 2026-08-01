# Phase 0: Scaffold and Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the repository, freeze the CSV contract and the `FeaturePanel` type, and ship a synthetic data generator — so that Joash can start on models on day one of Sprint 1 without waiting for real data or for the ingestion code to be finished.

**Architecture:** A pure-Python package under `src/forecasting_engine/` with no Streamlit dependency. Phase 0 builds only the left edge of the pipeline: schema → loader → `align_and_lag()` → `FeaturePanel`. Look-ahead bias is prevented by construction — `FeaturePanel` is frozen, validates its own invariants, and is reachable only through `align_and_lag()`.

**Tech Stack:** Python 3.11+, pandas, numpy, pytest, ruff, uv. No modelling libraries yet — they arrive in the sprint that needs them.

**Reference spec:** `docs/superpowers/specs/2026-07-29-forecasting-engine-architecture-design.md`

---

## Deviations from the spec

Two implementation-time decisions differ from the spec text. Both are noted here so the spec can be updated when this plan lands.

1. **Schema validation is hand-rolled, not pandera.** The spec says `schema.py # column contract (pandera)`. A ~70-line validator returning a list of `SchemaIssue` records has zero dependency-version risk and produces exactly the structured output the Sprint 1 `QualityReport` deliverable needs. Pandera would be a second way to describe the same contract.

2. **The `bfill`/`interpolate` ban is a test, not a lint rule.** The spec says "banned by a lint rule". Ruff has no rule for banning specific pandas methods. A source-scanning pytest is simpler, has no plugin dependency, and fails loudly in CI with a message that explains *why*.

## Working rules for every task

- Work on the `phase-0-ingestion` branch, never directly on `main`.
- Before every commit, run `uv run ruff format .` and include the result. CI runs
  `ruff format --check` and will fail otherwise. The code blocks in this plan are
  written for readability and are not guaranteed to match the formatter's output
  byte for byte — let the formatter win.
- Run `uv run pytest -v` and read the output. A task is not done because the code
  was written; it is done because the tests ran and passed.

## File structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Dependencies, build config, ruff and pytest settings |
| `.gitignore` | Standard Python + data directory |
| `.github/workflows/ci.yml` | ruff + pytest on every push |
| `docs/data-specification.md` | Human-readable CSV contract — a sponsor deliverable |
| `src/forecasting_engine/__init__.py` | Package marker, version |
| `src/forecasting_engine/ingest/schema.py` | Column contract as code, `validate()` |
| `src/forecasting_engine/ingest/provenance.py` | `SourceFile`, `Provenance` — shared by loader and panel |
| `src/forecasting_engine/ingest/loader.py` | CSV → `RawFrame`, raises on blocking issues |
| `src/forecasting_engine/ingest/panel.py` | `FeaturePanel` type and its invariants |
| `src/forecasting_engine/ingest/align.py` | `align_and_lag()` — the only producer of `FeaturePanel` |
| `src/forecasting_engine/fixtures.py` | Synthetic data generator + CLI |
| `src/forecasting_engine/config.py` | `RunConfig` and its component specs |

`panel.py` and `provenance.py` are additions to the layout in the spec. The spec put `FeaturePanel` inside `align.py`; separating the type from the transformation keeps both files small and lets `loader.py` import `SourceFile` without a cycle.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.github/workflows/ci.yml`
- Create: `src/forecasting_engine/__init__.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Install uv**

`uv` is not currently installed on this machine. Either works:

```bash
brew install uv
```

Verify:

```bash
uv --version
```

Expected: a version string such as `uv 0.5.x`. If `brew` is unavailable, use `curl -LsSf https://astral.sh/uv/install.sh | sh` and restart the shell.

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "forecasting-engine"
version = "0.1.0"
description = "Forecasting engine for strategic asset allocation"
requires-python = ">=3.11"
dependencies = [
    "pandas>=2.2",
    "numpy>=1.26",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.6",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/forecasting_engine"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]
# docs/ holds illustrative snippets that reference types defined elsewhere, and
# notebooks/ holds research. Ruff formats Markdown code fences and .ipynb files
# natively, so without these both would gate CI on prose and exploration.
extend-exclude = ["docs", "notebooks"]
force-exclude = true

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

Modelling libraries are deliberately absent. Each sprint adds only what it uses.

The exclusions are not optional. Ruff 0.16 formats Python code fences inside
Markdown and lints `.ipynb` natively, so a `ruff format --check` gate without
them fails on the design spec's deliberately column-aligned dataclasses, and
later on any research notebook. `force-exclude` extends the same protection to
explicitly-targeted invocations such as a pre-commit hook or format-on-save.

- [ ] **Step 3: Write `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
*.egg-info/
dist/
build/
data/
.ipynb_checkpoints/
.DS_Store
```

`data/` is ignored: generated fixtures and institutional exports never enter git.

- [ ] **Step 4: Create the package and a smoke test**

`src/forecasting_engine/__init__.py`:

```python
"""Forecasting engine for strategic asset allocation."""

__version__ = "0.1.0"
```

`tests/test_smoke.py`:

```python
import forecasting_engine


def test_package_imports():
    assert forecasting_engine.__version__ == "0.1.0"
```

- [ ] **Step 5: Install and run the test**

```bash
uv sync --all-extras
uv run pytest tests/test_smoke.py -v
```

Expected: `1 passed`. If the import fails, the `[tool.hatch.build.targets.wheel]` packages path is wrong.

- [ ] **Step 6: Write the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Install
        run: uv sync --all-extras --locked
      - name: Lint
        run: uv run ruff check .
      - name: Format
        run: uv run ruff format --check .
      - name: Test
        run: uv run pytest -v
```

`on: push:` with no branch filter is deliberate. Work happens on feature
branches, so filtering to `main` would mean no commit is ever checked until a
pull request exists. `--locked` makes CI fail loudly if `pyproject.toml` and
`uv.lock` have drifted rather than silently re-resolving.

Also create `.python-version` so both developers and CI resolve the same
interpreter (uv downloads it automatically if absent):

```
3.13
```

- [ ] **Step 7: Verify lint passes locally**

```bash
uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore .github/ src/ tests/ uv.lock
git commit -m "chore: project scaffold with uv, pytest and ruff"
git push origin phase-0-ingestion
```

---

### Task 2: Data specification document

This is a named sponsor deliverable and the human-readable twin of `schema.py`. Write it first so the code has something to conform to.

**Files:**
- Create: `docs/data-specification.md`

- [ ] **Step 1: Write the document**

````markdown
# Data Specification

The forecasting engine accepts a single CSV of daily market and macroeconomic
signals. This document is the contract. `src/forecasting_engine/ingest/schema.py`
is the machine-readable version of the same contract — if you change one, change
the other.

## File format

- UTF-8 encoded CSV with a header row
- One row per trading day, ascending by date
- No thousands separators, no currency symbols, no percent signs

## Columns

All columns are required.

| Column | Type | Range | Description |
|---|---|---|---|
| `date` | ISO date (`YYYY-MM-DD`) | — | Trading date. Unique, ascending. |
| `spx_close` | float | > 0 | S&P 500 index close |
| `agg_close` | float | > 0 | Bloomberg Global Aggregate Bond Index close |
| `vix` | float | 0 – 200 | CBOE Volatility Index |
| `credit_spread_hy` | float | 0 – 50 | ICE BofA US High Yield option-adjusted spread, percent |
| `credit_spread_ig` | float | 0 – 20 | ICE BofA US Investment Grade option-adjusted spread, percent |
| `fx_impl_vol` | float | 0 – 100 | G7 FX implied volatility index |
| `breakeven_10y` | float | -5 – 15 | 10-year inflation breakeven rate, percent |
| `term_spread` | float | -10 – 10 | 10-year minus 2-year Treasury yield, percent |

Percent columns are expressed in percentage points: a 3.5% spread is `3.5`, not
`0.035`.

## How violations are treated

Not every violation makes a file unusable. There are two classes.

**Rejected.** A missing column, an unparseable date, or a non-numeric value in a
numeric column. The file cannot be interpreted, so it is refused outright.

**Repaired and reported.** Out-of-order rows are sorted. Duplicate dates are
resolved by keeping the last occurrence, on the assumption that a repeated date
is a revision rather than a mistake. Values outside the ranges above are flagged
but retained — a genuine market dislocation looks a lot like an outlier, and
dropping it would hide exactly the events the model most needs to see.

No repair is silent. Every one is counted in the data quality report.

## What the system does with this file

Forward return targets are **derived, never supplied**. `spx_fwd_5d` and
`agg_fwd_5d` are computed from `spx_close` and `agg_close`. Do not add target
columns to the input. Unknown columns are ignored rather than rejected, so a
supplied target would be silently discarded rather than used.

Every signal column is shifted forward by at least one trading day before any
model sees it, so a row dated `t` carries the signal value observed at `t-1`.
This is applied centrally and cannot be bypassed.

## Missing values

Forward-fill only, capped at 5 consecutive days. Longer gaps are dropped and
reported. Backward-fill and interpolation are prohibited — both pull future
information into the past.

A signal that did not yet exist on a given date is missing, not zero. Do not
back-fill history for a series that started later; leave the cells empty.

## Point-in-time dating

Revised macroeconomic series must be dated to their **release date**, not their
reference period. CPI for March released on 10 April belongs on the row dated
10 April. FRED/ALFRED vintages provide this.

## Known-defect test file

`python -m forecasting_engine.fixtures` writes a synthetic file matching this
specification, including deliberate duplicates, a date gap, missing cells and a
crash window. Use it to exercise the quality checks. Pass `--clean` for a
defect-free file.
````

- [ ] **Step 2: Commit**

```bash
git add docs/data-specification.md
git commit -m "docs: CSV data specification"
git push origin phase-0-ingestion
```

---

### Task 3: Column schema and validator

**Files:**
- Create: `src/forecasting_engine/ingest/__init__.py`
- Create: `src/forecasting_engine/ingest/schema.py`
- Test: `tests/unit/test_schema.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_schema.py`:

```python
import pandas as pd

from forecasting_engine.ingest import schema


def valid_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "spx_close": [100.0, 101.0, 102.0],
            "agg_close": [50.0, 50.1, 50.2],
            "vix": [15.0, 16.0, 17.0],
            "credit_spread_hy": [3.5, 3.6, 3.7],
            "credit_spread_ig": [1.2, 1.2, 1.3],
            "fx_impl_vol": [8.0, 8.1, 8.2],
            "breakeven_10y": [2.2, 2.2, 2.3],
            "term_spread": [1.0, 1.0, 1.1],
        }
    )


def test_valid_frame_has_no_issues():
    assert schema.validate(valid_frame()) == []


def test_missing_column_is_reported():
    frame = valid_frame().drop(columns=["vix"])
    issues = schema.validate(frame)
    assert [i.kind for i in issues] == ["missing_column"]
    assert issues[0].column == "vix"


def test_duplicate_date_is_reported():
    frame = valid_frame()
    frame.loc[2, "date"] = "2024-01-02"
    kinds = {i.kind for i in schema.validate(frame)}
    assert "duplicate_date" in kinds


def test_unsorted_dates_are_reported():
    frame = valid_frame()
    frame["date"] = ["2024-01-03", "2024-01-02", "2024-01-01"]
    kinds = {i.kind for i in schema.validate(frame)}
    assert "unsorted_dates" in kinds


def test_negative_vix_is_out_of_range():
    frame = valid_frame()
    frame.loc[1, "vix"] = -3.0
    issues = [i for i in schema.validate(frame) if i.kind == "out_of_range"]
    assert len(issues) == 1
    assert issues[0].column == "vix"
    assert issues[0].count == 1


def test_non_numeric_value_is_reported():
    frame = valid_frame()
    frame["vix"] = frame["vix"].astype(object)
    frame.loc[1, "vix"] = "not a number"
    kinds = {i.kind for i in schema.validate(frame)}
    assert "non_numeric" in kinds


def test_blank_cell_is_not_a_non_numeric_error():
    frame = valid_frame()
    frame.loc[1, "vix"] = None
    kinds = {i.kind for i in schema.validate(frame)}
    assert "non_numeric" not in kinds


def test_signal_columns_exclude_prices():
    assert "spx_close" not in schema.SIGNAL_COLUMNS
    assert "vix" in schema.SIGNAL_COLUMNS


def test_missing_date_does_not_hide_other_problems():
    frame = valid_frame().drop(columns=["date"])
    frame.loc[1, "vix"] = 300.0
    kinds = {i.kind for i in schema.validate(frame)}
    assert kinds == {"missing_column", "out_of_range"}


def test_missing_column_detail_names_the_series():
    frame = valid_frame().drop(columns=["credit_spread_hy"])
    detail = schema.validate(frame)[0].detail
    assert "credit_spread_hy" in detail
    assert "HY OAS" in detail


def test_unparseable_date_is_reported():
    frame = valid_frame()
    frame.loc[1, "date"] = "not-a-date"
    issues = [i for i in schema.validate(frame) if i.kind == "unparseable_date"]
    assert len(issues) == 1
    assert issues[0].count == 1


def test_value_above_the_ceiling_is_out_of_range():
    frame = valid_frame()
    frame.loc[1, "vix"] = 300.0
    issues = [i for i in schema.validate(frame) if i.kind == "out_of_range"]
    assert len(issues) == 1
    assert "above" in issues[0].detail


def test_multiple_issues_accumulate():
    frame = valid_frame()
    frame.loc[1, "vix"] = -3.0
    frame["term_spread"] = frame["term_spread"].astype(object)
    frame.loc[2, "term_spread"] = "oops"
    kinds = {i.kind for i in schema.validate(frame)}
    assert {"out_of_range", "non_numeric"} <= kinds


def test_blocking_keeps_only_unusable_issues():
    issues = [
        schema.SchemaIssue("missing_column", "vix", "absent"),
        schema.SchemaIssue("duplicate_date", "date", "repeated"),
        schema.SchemaIssue("non_numeric", "vix", "bad"),
    ]
    assert [i.kind for i in schema.blocking(issues)] == ["missing_column", "non_numeric"]


def test_repairable_issues_are_not_blocking():
    issues = [
        schema.SchemaIssue("duplicate_date", "date", "repeated"),
        schema.SchemaIssue("unsorted_dates", "date", "unsorted"),
        schema.SchemaIssue("out_of_range", "vix", "high"),
    ]
    assert schema.blocking(issues) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_schema.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'forecasting_engine.ingest'`

- [ ] **Step 3: Write the implementation**

`src/forecasting_engine/ingest/__init__.py`:

```python
"""Data ingestion: schema validation, loading, alignment."""
```

`src/forecasting_engine/ingest/schema.py`:

```python
"""The column contract for uploaded signal CSVs.

This module is the single source of truth for what a valid input file looks
like. ``docs/data-specification.md`` is the human-readable twin; change both or
neither.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DATE_COLUMN = "date"


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    minimum: float | None = None
    maximum: float | None = None
    description: str = ""


@dataclass(frozen=True)
class SchemaIssue:
    """One problem found in an input file.

    ``kind`` is a stable machine-readable tag; ``detail`` is shown to the user.
    """

    kind: str
    column: str
    detail: str
    count: int = 1


PRICE_COLUMNS: tuple[str, ...] = ("spx_close", "agg_close")

COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("spx_close", minimum=0.0, description="S&P 500 index close"),
    ColumnSpec("agg_close", minimum=0.0, description="Bloomberg Global Aggregate close"),
    ColumnSpec("vix", minimum=0.0, maximum=200.0, description="CBOE Volatility Index"),
    ColumnSpec("credit_spread_hy", minimum=0.0, maximum=50.0, description="US HY OAS, percent"),
    ColumnSpec("credit_spread_ig", minimum=0.0, maximum=20.0, description="US IG OAS, percent"),
    ColumnSpec("fx_impl_vol", minimum=0.0, maximum=100.0, description="G7 FX implied volatility"),
    ColumnSpec("breakeven_10y", minimum=-5.0, maximum=15.0, description="10y breakeven, percent"),
    ColumnSpec("term_spread", minimum=-10.0, maximum=10.0, description="10y minus 2y, percent"),
)

SIGNAL_COLUMNS: tuple[str, ...] = tuple(c.name for c in COLUMNS if c.name not in PRICE_COLUMNS)
REQUIRED_COLUMNS: tuple[str, ...] = (DATE_COLUMN,) + tuple(c.name for c in COLUMNS)

#: Issue kinds that make a file unusable rather than merely imperfect.
BLOCKING_KINDS: frozenset[str] = frozenset({"missing_column", "unparseable_date", "non_numeric"})

_BY_NAME: dict[str, ColumnSpec] = {spec.name: spec for spec in COLUMNS}


def validate(frame: pd.DataFrame) -> list[SchemaIssue]:
    """Return every contract violation in ``frame``. An empty list means valid.

    Every column is checked independently, so one missing column never hides a
    problem in another. A user fixing a malformed file should see the whole list
    at once rather than discovering it one round at a time.
    """
    issues: list[SchemaIssue] = []

    missing = [name for name in REQUIRED_COLUMNS if name not in frame.columns]
    issues.extend(SchemaIssue("missing_column", name, _absent_detail(name)) for name in missing)

    if DATE_COLUMN not in missing:
        issues.extend(_date_issues(frame[DATE_COLUMN]))
    for spec in COLUMNS:
        if spec.name in frame.columns:
            issues.extend(_numeric_issues(frame[spec.name], spec))
    return issues


def _absent_detail(name: str) -> str:
    """Name the series as well as the column, since the reader may not know the code."""
    spec = _BY_NAME.get(name)
    if spec is None or not spec.description:
        return f"required column {name!r} is absent"
    return f"required column {name!r} ({spec.description}) is absent"


def _date_issues(raw: pd.Series) -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []
    dates = pd.to_datetime(raw, errors="coerce")

    # As with numeric columns, a blank cell is missing data rather than a bad
    # value. Subtracting the original NaN count leaves only genuine parse errors.
    unparseable = int(dates.isna().sum() - raw.isna().sum())
    if unparseable > 0:
        issues.append(
            SchemaIssue("unparseable_date", DATE_COLUMN, "values are not valid dates", unparseable)
        )

    duplicates = int(dates.duplicated().sum())
    if duplicates:
        issues.append(SchemaIssue("duplicate_date", DATE_COLUMN, "repeated dates", duplicates))

    present = dates.dropna()
    if not present.is_monotonic_increasing:
        issues.append(SchemaIssue("unsorted_dates", DATE_COLUMN, "dates are not ascending"))
    return issues


def _numeric_issues(raw: pd.Series, spec: ColumnSpec) -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []
    values = pd.to_numeric(raw, errors="coerce")

    # A blank cell is missing data, not a type error — quality.py handles those.
    unparseable = int(values.isna().sum() - raw.isna().sum())
    if unparseable > 0:
        issues.append(SchemaIssue("non_numeric", spec.name, "values are not numeric", unparseable))

    if spec.minimum is not None:
        below = int((values < spec.minimum).sum())
        if below:
            issues.append(
                SchemaIssue("out_of_range", spec.name, f"values below {spec.minimum}", below)
            )
    if spec.maximum is not None:
        above = int((values > spec.maximum).sum())
        if above:
            issues.append(
                SchemaIssue("out_of_range", spec.name, f"values above {spec.maximum}", above)
            )
    return issues


def blocking(issues: list[SchemaIssue]) -> list[SchemaIssue]:
    """Filter to the issues that make a file unusable."""
    return [issue for issue in issues if issue.kind in BLOCKING_KINDS]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_schema.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add src/forecasting_engine/ingest/ tests/unit/test_schema.py
git commit -m "feat: column contract and schema validator"
git push origin phase-0-ingestion
```

---

### Task 4: Synthetic fixture generator

Built before the loader so the loader has realistic input to be tested against.

**Files:**
- Create: `src/forecasting_engine/fixtures.py`
- Test: `tests/unit/test_fixtures.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_fixtures.py`:

```python
import pandas as pd

from forecasting_engine import fixtures
from forecasting_engine.ingest import schema


def test_clean_frame_satisfies_the_schema():
    frame = fixtures.generate(years=2, seed=1, with_defects=False)
    assert schema.validate(frame) == []


def test_generation_is_deterministic():
    first = fixtures.generate(years=2, seed=7, with_defects=False)
    second = fixtures.generate(years=2, seed=7, with_defects=False)
    pd.testing.assert_frame_equal(first, second)


def test_different_seeds_give_different_data():
    first = fixtures.generate(years=2, seed=1, with_defects=False)
    second = fixtures.generate(years=2, seed=2, with_defects=False)
    assert not first["vix"].equals(second["vix"])


def test_all_required_columns_present():
    frame = fixtures.generate(years=2, seed=1, with_defects=False)
    assert set(schema.REQUIRED_COLUMNS) <= set(frame.columns)


def test_defective_frame_contains_duplicates_and_blanks():
    frame = fixtures.generate(years=5, seed=1, with_defects=True)
    kinds = {issue.kind for issue in schema.validate(frame)}
    assert "duplicate_date" in kinds
    assert frame.isna().any().any()


def test_crash_window_produces_a_large_drawdown():
    frame = fixtures.generate(years=5, seed=1, with_defects=False)
    worst = frame["spx_close"].pct_change(20).min()
    assert worst < -0.15, f"expected a stress window, worst 20-day move was {worst:.1%}"


def test_cli_writes_a_readable_file(tmp_path):
    out = tmp_path / "signals.csv"
    exit_code = fixtures.main(["--years", "2", "--out", str(out), "--clean"])
    assert exit_code == 0
    written = pd.read_csv(out)
    assert schema.validate(written) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_fixtures.py -v
```

Expected: `ModuleNotFoundError: No module named 'forecasting_engine.fixtures'`

- [ ] **Step 3: Write the implementation**

`src/forecasting_engine/fixtures.py`:

```python
"""Synthetic market data matching ``docs/data-specification.md``.

Exists so the pipeline can be built and tested before institutional exports are
available. The default output deliberately contains the defects the quality
checks are supposed to catch.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from forecasting_engine.ingest.schema import DATE_COLUMN

TRADING_DAYS_PER_YEAR = 252
_CRASH_LENGTH = 30


def generate(years: int = 10, seed: int = 42, *, with_defects: bool = True) -> pd.DataFrame:
    """Build a synthetic signal file.

    A stress window sits one third of the way through the sample so crash-recall
    labels and drawdown metrics have something real to find.
    """
    rng = np.random.default_rng(seed)
    n = years * TRADING_DAYS_PER_YEAR
    dates = pd.bdate_range(end=pd.Timestamp("2025-12-31"), periods=n)

    stress = np.zeros(n)
    crash_start = n // 3
    stress[crash_start : crash_start + _CRASH_LENGTH] = 1.0

    vix = _volatility_path(rng, n, stress)
    daily_vol = vix / 100.0 / np.sqrt(TRADING_DAYS_PER_YEAR)

    equity_returns = rng.normal(0.0, 1.0, n) * daily_vol + 0.0003 - 0.012 * stress
    bond_returns = rng.normal(0.0001, 0.0025, n) + 0.002 * stress

    frame = pd.DataFrame(
        {
            DATE_COLUMN: dates,
            "spx_close": 3000.0 * np.exp(np.cumsum(equity_returns)),
            "agg_close": 100.0 * np.exp(np.cumsum(bond_returns)),
            "vix": vix,
            "credit_spread_hy": np.clip(
                3.5 + 0.12 * (vix - 16.0) + rng.normal(0, 0.08, n), 0.5, None
            ),
            "credit_spread_ig": np.clip(
                1.2 + 0.03 * (vix - 16.0) + rng.normal(0, 0.03, n), 0.2, None
            ),
            "fx_impl_vol": np.clip(8.0 + 0.25 * (vix - 16.0) + rng.normal(0, 0.3, n), 2.0, None),
            "breakeven_10y": 2.2 + np.cumsum(rng.normal(0, 0.004, n)),
            "term_spread": 1.0 + np.cumsum(rng.normal(0, 0.005, n)),
        }
    )
    return _inject_defects(frame) if with_defects else frame


def _volatility_path(rng: np.random.Generator, n: int, stress: np.ndarray) -> np.ndarray:
    """Mean-reverting VIX around 16, spiking through the stress window."""
    vix = np.empty(n)
    vix[0] = 16.0
    for i in range(1, n):
        shock = rng.normal(0.0, 1.1) + 8.0 * stress[i]
        vix[i] = max(9.0, vix[i - 1] + 0.06 * (16.0 - vix[i - 1]) + 0.35 * shock)
    return vix


def _inject_defects(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the flaws a real vendor export has, so the quality checks earn their keep.

    Positions are relative to the sample length so a one-year file gets the same
    treatment as a ten-year one.
    """
    frame = frame.copy()
    n = len(frame)

    gap_start = n // 2
    frame = frame.drop(frame.index[gap_start : gap_start + 4])

    duplicated = frame.iloc[sorted({n // 12, n // 3, (2 * n) // 3})]
    frame = pd.concat([frame, duplicated]).sort_values(DATE_COLUMN).reset_index(drop=True)

    blank_start = n // 6
    for offset, column in enumerate(("vix", "credit_spread_hy", "fx_impl_vol")):
        frame.loc[blank_start + offset, column] = np.nan
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic signal data.")
    parser.add_argument("--years", type=int, default=10, help="years of history (default: 10)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42)")
    parser.add_argument("--out", type=Path, default=Path("data/raw/signals.csv"))
    parser.add_argument("--clean", action="store_true", help="omit the deliberate defects")
    args = parser.parse_args(argv)

    frame = generate(years=args.years, seed=args.seed, with_defects=not args.clean)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False)
    print(f"wrote {len(frame)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_fixtures.py -v
```

Expected: `7 passed`. If `test_crash_window_produces_a_large_drawdown` fails, raise the `0.012` stress coefficient in `equity_returns` until a 20-day drop of at least 15% appears.

- [ ] **Step 5: Generate a real file and eyeball it**

```bash
uv run python -m forecasting_engine.fixtures --years 10
```

Expected: `wrote 2523 rows to data/raw/signals.csv` — 2520 business days plus 3 injected duplicates, minus the 4-day gap, is 2519; the printed count will be close to this and need not match exactly.

- [ ] **Step 6: Commit**

```bash
git add src/forecasting_engine/fixtures.py tests/unit/test_fixtures.py
git commit -m "feat: synthetic data generator with deliberate defects"
git push origin phase-0-ingestion
```

---

### Task 5: Provenance types and CSV loader

**Files:**
- Create: `src/forecasting_engine/ingest/provenance.py`
- Create: `src/forecasting_engine/ingest/loader.py`
- Test: `tests/unit/test_loader.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_loader.py`:

```python
import pandas as pd
import pytest

from forecasting_engine import fixtures
from forecasting_engine.ingest import loader


@pytest.fixture
def clean_csv(tmp_path):
    path = tmp_path / "clean.csv"
    fixtures.generate(years=2, seed=3, with_defects=False).to_csv(path, index=False)
    return path


@pytest.fixture
def defective_csv(tmp_path):
    path = tmp_path / "defective.csv"
    fixtures.generate(years=5, seed=3, with_defects=True).to_csv(path, index=False)
    return path


def test_clean_file_loads_with_no_issues(clean_csv):
    raw = loader.load(clean_csv)
    assert raw.issues == ()
    assert isinstance(raw.frame.index, pd.DatetimeIndex)
    assert raw.frame.index.is_monotonic_increasing


def test_source_records_a_content_hash(clean_csv):
    raw = loader.load(clean_csv)
    assert len(raw.source.sha256) == 64
    assert raw.source.rows == len(raw.frame)


def test_same_content_hashes_identically(clean_csv, tmp_path):
    copy = tmp_path / "copy.csv"
    copy.write_bytes(clean_csv.read_bytes())
    assert loader.load(clean_csv).source.sha256 == loader.load(copy).source.sha256


def test_duplicate_dates_are_dropped_keeping_the_last(defective_csv):
    raw = loader.load(defective_csv)
    assert not raw.frame.index.duplicated().any()


def test_repairable_issues_are_reported_not_raised(defective_csv):
    raw = loader.load(defective_csv)
    assert any(issue.kind == "duplicate_date" for issue in raw.issues)


def test_missing_column_raises(tmp_path):
    path = tmp_path / "broken.csv"
    fixtures.generate(years=2, seed=3, with_defects=False).drop(columns=["vix"]).to_csv(
        path, index=False
    )
    with pytest.raises(loader.SchemaError, match="vix"):
        loader.load(path)


def test_strict_false_allows_blocking_issues_through(tmp_path):
    path = tmp_path / "broken.csv"
    fixtures.generate(years=2, seed=3, with_defects=False).drop(columns=["vix"]).to_csv(
        path, index=False
    )
    raw = loader.load(path, strict=False)
    assert any(issue.kind == "missing_column" for issue in raw.issues)


def test_unsorted_input_is_sorted_on_load(tmp_path):
    path = tmp_path / "unsorted.csv"
    frame = fixtures.generate(years=2, seed=3, with_defects=False)
    frame.iloc[::-1].to_csv(path, index=False)
    raw = loader.load(path)
    assert raw.frame.index.is_monotonic_increasing
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_loader.py -v
```

Expected: `ModuleNotFoundError: No module named 'forecasting_engine.ingest.loader'`

- [ ] **Step 3: Write the implementation**

`src/forecasting_engine/ingest/provenance.py`:

```python
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
```

`src/forecasting_engine/ingest/loader.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_loader.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/forecasting_engine/ingest/provenance.py src/forecasting_engine/ingest/loader.py tests/unit/test_loader.py
git commit -m "feat: CSV loader with content hashing and schema enforcement"
git push origin phase-0-ingestion
```

---

### Task 6: The FeaturePanel type

The load-bearing piece. Everything downstream depends on this being right.

**Files:**
- Create: `src/forecasting_engine/ingest/panel.py`
- Test: `tests/unit/test_panel.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_panel.py`:

```python
from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from forecasting_engine.ingest.panel import FeaturePanel
from forecasting_engine.ingest.provenance import Provenance, SourceFile

PROV = Provenance(
    sources=(SourceFile(path="x.csv", sha256="a" * 64, rows=3),),
    built_at="2026-07-29T00:00:00+00:00",
    horizon_days=5,
)


def make_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"vix": [1.0, 2.0, 3.0], "spx_fwd_5d": [0.01, 0.02, 0.03]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )


def make_panel(**overrides) -> FeaturePanel:
    kwargs = {
        "frame": make_frame(),
        "signals": ("vix",),
        "targets": ("spx_fwd_5d",),
        "lag_days": 1,
        "provenance": PROV,
    }
    kwargs.update(overrides)
    return FeaturePanel(**kwargs)


def test_valid_panel_constructs():
    assert make_panel().lag_days == 1


def test_zero_lag_is_rejected():
    with pytest.raises(ValueError, match="look-ahead"):
        make_panel(lag_days=0)


def test_negative_lag_is_rejected():
    with pytest.raises(ValueError, match="look-ahead"):
        make_panel(lag_days=-1)


def test_a_column_cannot_be_both_signal_and_target():
    with pytest.raises(ValueError, match="both a signal and a target"):
        make_panel(signals=("vix", "spx_fwd_5d"))


def test_unknown_column_is_rejected():
    with pytest.raises(ValueError, match="not present"):
        make_panel(signals=("vix", "does_not_exist"))


def test_unsorted_index_is_rejected():
    frame = make_frame().iloc[::-1]
    with pytest.raises(ValueError, match="ascending"):
        make_panel(frame=frame)


def test_non_datetime_index_is_rejected():
    frame = make_frame().reset_index(drop=True)
    with pytest.raises(ValueError, match="DatetimeIndex"):
        make_panel(frame=frame)


def test_panel_is_immutable():
    panel = make_panel()
    with pytest.raises(FrozenInstanceError):
        panel.lag_days = 2


def test_matrix_returns_signals_and_one_target():
    panel = make_panel()
    features, target = panel.matrix(panel.frame.index, "spx_fwd_5d")
    assert list(features.columns) == ["vix"]
    assert len(target) == 3
    assert target.name == "spx_fwd_5d"


def test_matrix_defaults_to_the_first_target():
    panel = make_panel()
    _, target = panel.matrix(panel.frame.index)
    assert target.name == "spx_fwd_5d"


def test_matrix_rejects_an_unknown_target():
    panel = make_panel()
    with pytest.raises(KeyError, match="nope"):
        panel.matrix(panel.frame.index, "nope")


def test_matrix_never_leaks_a_target_into_the_features():
    panel = make_panel()
    features, _ = panel.matrix(panel.frame.index)
    assert not set(features.columns) & set(panel.targets)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_panel.py -v
```

Expected: `ModuleNotFoundError: No module named 'forecasting_engine.ingest.panel'`

- [ ] **Step 3: Write the implementation**

`src/forecasting_engine/ingest/panel.py`:

```python
"""The lag-safe dataset every model consumes.

A FeaturePanel is the only thing a Forecaster is allowed to see. It is frozen,
it checks its own invariants on construction, and the sole way to build a
correct one is ``align_and_lag``. There is deliberately no way to hand a model a
bare DataFrame.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from forecasting_engine.ingest.provenance import Provenance


@dataclass(frozen=True)
class FeaturePanel:
    """Lagged signals and forward targets on a shared date index.

    A row dated ``t`` holds signal values observed at ``t - lag_days`` and the
    return realised between ``t`` and ``t + horizon_days``. Predicting the target
    from the signals therefore uses no information from after ``t - lag_days``.
    """

    frame: pd.DataFrame
    signals: tuple[str, ...]
    targets: tuple[str, ...]
    lag_days: int
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.lag_days < 1:
            raise ValueError(
                f"lag_days must be at least 1 to prevent look-ahead bias, got {self.lag_days}"
            )
        if not isinstance(self.frame.index, pd.DatetimeIndex):
            raise ValueError(
                f"frame must have a DatetimeIndex, got {type(self.frame.index).__name__}"
            )
        if not self.frame.index.is_monotonic_increasing:
            raise ValueError("frame index must be sorted in ascending date order")

        overlap = set(self.signals) & set(self.targets)
        if overlap:
            raise ValueError(f"{sorted(overlap)} are declared as both a signal and a target")

        absent = (set(self.signals) | set(self.targets)) - set(self.frame.columns)
        if absent:
            raise ValueError(f"declared columns not present in frame: {sorted(absent)}")

    def matrix(
        self, index: pd.DatetimeIndex, target: str | None = None
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Return ``(features, target)`` for ``index``.

        This is the only accessor models should use. It cannot return a target
        column among the features.
        """
        name = target if target is not None else self.targets[0]
        if name not in self.targets:
            raise KeyError(
                f"{name!r} is not a target of this panel; available: {list(self.targets)}"
            )
        rows = self.frame.loc[index]
        return rows[list(self.signals)], rows[name]

    @property
    def horizon_days(self) -> int:
        return self.provenance.horizon_days

    def __len__(self) -> int:
        return len(self.frame)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_panel.py -v
```

Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add src/forecasting_engine/ingest/panel.py tests/unit/test_panel.py
git commit -m "feat: FeaturePanel with self-validating lag invariants"
git push origin phase-0-ingestion
```

---

### Task 7: align_and_lag

**Files:**
- Create: `src/forecasting_engine/ingest/align.py`
- Test: `tests/unit/test_align.py`

- [ ] **Step 1: Write the failing test**

The arithmetic is checked against hand-computed values on a frame small enough to verify by eye. Closes run 100, 101, … 119 and VIX runs 10, 11, … 29 across 20 business days.

`tests/unit/test_align.py`:

```python
import numpy as np
import pandas as pd
import pytest

from forecasting_engine.ingest.align import align_and_lag
from forecasting_engine.ingest.loader import RawFrame
from forecasting_engine.ingest.provenance import SourceFile

SOURCE = SourceFile(path="synthetic.csv", sha256="b" * 64, rows=20)


def ramp_raw(n: int = 20) -> RawFrame:
    """Closes 100..119 and VIX 10..29 on consecutive business days."""
    index = pd.bdate_range("2024-01-01", periods=n)
    frame = pd.DataFrame(
        {
            "spx_close": np.arange(100.0, 100.0 + n),
            "agg_close": np.arange(50.0, 50.0 + n),
            "vix": np.arange(10.0, 10.0 + n),
            "credit_spread_hy": np.full(n, 3.5),
            "credit_spread_ig": np.full(n, 1.2),
            "fx_impl_vol": np.full(n, 8.0),
            "breakeven_10y": np.full(n, 2.2),
            "term_spread": np.full(n, 1.0),
        },
        index=index,
    )
    frame.index.name = "date"
    return RawFrame(frame=frame, source=SOURCE, issues=())


def test_signal_carries_the_previous_days_value():
    panel = align_and_lag(ramp_raw(), horizon_days=5, lag_days=1)
    # Row index 5 of the raw frame is date d5; after a one-day lag its VIX is d4's value, 14.0
    d5 = pd.bdate_range("2024-01-01", periods=20)[5]
    assert panel.frame.loc[d5, "vix"] == pytest.approx(14.0)


def test_target_is_the_forward_return_over_the_horizon():
    panel = align_and_lag(ramp_raw(), horizon_days=5, lag_days=1)
    d5 = pd.bdate_range("2024-01-01", periods=20)[5]
    # close[d10] / close[d5] - 1 == 110 / 105 - 1
    assert panel.frame.loc[d5, "spx_fwd_5d"] == pytest.approx(110.0 / 105.0 - 1.0)


def test_two_day_lag_shifts_one_day_further():
    panel = align_and_lag(ramp_raw(), horizon_days=5, lag_days=2)
    d5 = pd.bdate_range("2024-01-01", periods=20)[5]
    assert panel.frame.loc[d5, "vix"] == pytest.approx(13.0)


def test_rows_without_a_full_target_window_are_dropped():
    panel = align_and_lag(ramp_raw(20), horizon_days=5, lag_days=1)
    # 20 rows, minus 1 leading row with no lagged signal, minus 5 trailing rows
    # with no realised forward return.
    assert len(panel) == 14


def test_target_names_encode_the_horizon():
    panel = align_and_lag(ramp_raw(), horizon_days=3, lag_days=1)
    assert panel.targets == ("spx_fwd_3d", "agg_fwd_3d")


def test_signals_exclude_price_columns():
    panel = align_and_lag(ramp_raw(), horizon_days=5, lag_days=1)
    assert "spx_close" not in panel.signals
    assert "vix" in panel.signals


def test_zero_lag_is_refused():
    with pytest.raises(ValueError, match="look-ahead"):
        align_and_lag(ramp_raw(), lag_days=0)


def test_zero_horizon_is_refused():
    with pytest.raises(ValueError, match="horizon_days"):
        align_and_lag(ramp_raw(), horizon_days=0)


def test_provenance_records_the_source_and_horizon():
    panel = align_and_lag(ramp_raw(), horizon_days=5, lag_days=1)
    assert panel.provenance.sources == (SOURCE,)
    assert panel.provenance.horizon_days == 5


def test_gaps_are_forward_filled_up_to_the_limit():
    raw = ramp_raw()
    frame = raw.frame.copy()
    frame.iloc[3:5, frame.columns.get_loc("vix")] = np.nan
    filled = align_and_lag(
        RawFrame(frame=frame, source=SOURCE, issues=()), horizon_days=5, lag_days=1
    )
    d5 = pd.bdate_range("2024-01-01", periods=20)[5]
    # d3 and d4 are blank, so they carry d2's value of 12.0; row d5 sees d4.
    assert filled.frame.loc[d5, "vix"] == pytest.approx(12.0)


def test_gaps_longer_than_the_limit_drop_the_row():
    raw = ramp_raw()
    frame = raw.frame.copy()
    frame.iloc[3:12, frame.columns.get_loc("vix")] = np.nan
    panel = align_and_lag(
        RawFrame(frame=frame, source=SOURCE, issues=()),
        horizon_days=5,
        lag_days=1,
        ffill_limit=2,
    )
    dates = pd.bdate_range("2024-01-01", periods=20)
    assert dates[8] not in panel.frame.index


def test_result_is_deterministic():
    first = align_and_lag(ramp_raw(), horizon_days=5, lag_days=1)
    second = align_and_lag(ramp_raw(), horizon_days=5, lag_days=1)
    pd.testing.assert_frame_equal(first.frame, second.frame)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_align.py -v
```

Expected: `ModuleNotFoundError: No module named 'forecasting_engine.ingest.align'`

- [ ] **Step 3: Write the implementation**

`src/forecasting_engine/ingest/align.py`:

```python
"""The single gate between raw data and anything that models it.

Every rule that prevents look-ahead bias lives here, applied once, centrally.
Nothing downstream shifts a series, fills a gap, or builds a target.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from forecasting_engine.ingest.loader import RawFrame
from forecasting_engine.ingest.panel import FeaturePanel
from forecasting_engine.ingest.provenance import Provenance
from forecasting_engine.ingest.schema import PRICE_COLUMNS, SIGNAL_COLUMNS

DEFAULT_HORIZON_DAYS = 5
DEFAULT_LAG_DAYS = 1
DEFAULT_FFILL_LIMIT = 5


def align_and_lag(
    raw: RawFrame,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    lag_days: int = DEFAULT_LAG_DAYS,
    ffill_limit: int = DEFAULT_FFILL_LIMIT,
) -> FeaturePanel:
    """Turn a loaded file into a lag-safe panel.

    Signals are shifted forward by ``lag_days`` so a row dated ``t`` carries only
    what was observable at ``t - lag_days``. Targets are the forward return from
    ``t`` to ``t + horizon_days``. Rows without both are dropped.

    Forward-fill only, capped at ``ffill_limit``. Backward-fill and interpolation
    are prohibited: both move future values into the past.
    """
    if lag_days < 1:
        raise ValueError(f"lag_days must be at least 1 to prevent look-ahead bias, got {lag_days}")
    if horizon_days < 1:
        raise ValueError(f"horizon_days must be at least 1, got {horizon_days}")

    frame = raw.frame.sort_index().ffill(limit=ffill_limit)

    targets = {
        _target_name(price, horizon_days): frame[price]
        .pct_change(periods=horizon_days)
        .shift(-horizon_days)
        for price in PRICE_COLUMNS
        if price in frame.columns
    }
    signals = tuple(name for name in SIGNAL_COLUMNS if name in frame.columns)

    combined = pd.concat(
        [frame[list(signals)].shift(lag_days), pd.DataFrame(targets, index=frame.index)],
        axis=1,
    ).dropna(how="any")

    return FeaturePanel(
        frame=combined,
        signals=signals,
        targets=tuple(targets),
        lag_days=lag_days,
        provenance=Provenance(
            sources=(raw.source,),
            built_at=datetime.now(UTC).isoformat(),
            horizon_days=horizon_days,
        ),
    )


def _target_name(price_column: str, horizon_days: int) -> str:
    """``spx_close`` with a 5-day horizon becomes ``spx_fwd_5d``."""
    stem = price_column.removesuffix("_close")
    return f"{stem}_fwd_{horizon_days}d"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_align.py -v
```

Expected: `12 passed`

Note: `from datetime import UTC` requires Python 3.11+, which `requires-python` already enforces.

- [ ] **Step 5: Commit**

```bash
git add src/forecasting_engine/ingest/align.py tests/unit/test_align.py
git commit -m "feat: align_and_lag, the single look-ahead prevention gate"
git push origin phase-0-ingestion
```

---

### Task 8: Leak-prevention guards

These tests protect the invariant against future edits, including edits made by someone who has not read this plan.

**Files:**
- Create: `tests/unit/test_no_leakage.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_no_leakage.py`:

```python
"""Guards against look-ahead bias creeping back in.

Success Criterion 1 of the project proposal requires look-ahead bias to be
structurally prevented. These tests are that structure.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from forecasting_engine.ingest.align import align_and_lag
from forecasting_engine.ingest.loader import RawFrame
from forecasting_engine.ingest.provenance import SourceFile

SRC = Path(__file__).resolve().parents[2] / "src"
BANNED = ("bfill(", "backfill(", "fillna(method=", "interpolate(")

SOURCE = SourceFile(path="synthetic.csv", sha256="c" * 64, rows=40)


def canary_raw(n: int = 40) -> RawFrame:
    """A frame whose VIX column is a perfect copy of a *future* price.

    If any code path fails to lag, the canary shows up as a signal that matches
    a value it could not possibly have known.
    """
    index = pd.bdate_range("2024-01-01", periods=n)
    closes = np.linspace(100.0, 200.0, n)
    frame = pd.DataFrame(
        {
            "spx_close": closes,
            "agg_close": np.linspace(50.0, 60.0, n),
            "vix": closes,  # the canary
            "credit_spread_hy": np.full(n, 3.5),
            "credit_spread_ig": np.full(n, 1.2),
            "fx_impl_vol": np.full(n, 8.0),
            "breakeven_10y": np.full(n, 2.2),
            "term_spread": np.full(n, 1.0),
        },
        index=index,
    )
    frame.index.name = "date"
    return RawFrame(frame=frame, source=SOURCE, issues=())


def test_source_contains_no_backward_filling():
    offenders = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in BANNED:
            if token in text:
                offenders.append(f"{path.relative_to(SRC)} uses {token}")
    assert not offenders, (
        "Backward-fill and interpolation move future values into the past, which is "
        "exactly the look-ahead bias this project is required to prevent. "
        "Use ffill with a cap instead. Offenders: " + "; ".join(offenders)
    )


def test_only_align_and_lag_constructs_a_panel():
    """FeaturePanel(...) should appear in panel.py, align.py and tests — nowhere else."""
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if "FeaturePanel(" in path.read_text(encoding="utf-8")
        and path.name not in {"panel.py", "align.py"}
    ]
    assert not offenders, (
        "FeaturePanel must only be constructed by align_and_lag so the lag is applied "
        f"exactly once. Offenders: {offenders}"
    )


def test_lagged_signal_never_equals_the_same_day_raw_value():
    raw = canary_raw()
    panel = align_and_lag(raw, horizon_days=5, lag_days=1)
    same_day = raw.frame.loc[panel.frame.index, "vix"]
    assert not np.allclose(panel.frame["vix"].to_numpy(), same_day.to_numpy()), (
        "the panel's signal column matches the same day's raw value, so no lag was applied"
    )


def test_lagged_signal_equals_the_previous_raw_value_exactly():
    raw = canary_raw()
    panel = align_and_lag(raw, horizon_days=5, lag_days=1)
    expected = raw.frame["vix"].shift(1).loc[panel.frame.index]
    np.testing.assert_allclose(panel.frame["vix"].to_numpy(), expected.to_numpy())


def test_extra_lag_changes_the_data():
    """The lag-shift audit from Risk 2, as an automated check."""
    raw = canary_raw()
    one = align_and_lag(raw, horizon_days=5, lag_days=1)
    two = align_and_lag(raw, horizon_days=5, lag_days=2)
    shared = one.frame.index.intersection(two.frame.index)
    assert not np.allclose(
        one.frame.loc[shared, "vix"].to_numpy(), two.frame.loc[shared, "vix"].to_numpy()
    ), "changing lag_days had no effect, so the lag is not being applied"


def test_no_target_is_reachable_as_a_signal():
    panel = align_and_lag(canary_raw(), horizon_days=5, lag_days=1)
    features, _ = panel.matrix(panel.frame.index)
    assert not set(features.columns) & set(panel.targets)


def test_final_rows_without_a_realised_return_are_absent():
    raw = canary_raw(40)
    panel = align_and_lag(raw, horizon_days=5, lag_days=1)
    assert panel.frame.index.max() <= raw.frame.index[-6], (
        "a row survived whose forward return had not yet happened"
    )
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/unit/test_no_leakage.py -v
```

Expected: `7 passed`. If `test_source_contains_no_backward_filling` fails, the offending file must be rewritten to use `ffill(limit=...)` — do not add an exemption.

- [ ] **Step 3: Prove the guard actually catches a regression**

Temporarily break the lag to confirm the tests are not vacuous:

```bash
sed -i '' 's/\.shift(lag_days)/.shift(0)/' src/forecasting_engine/ingest/align.py
uv run pytest tests/unit/test_no_leakage.py -q
```

Expected: FAILURES — at minimum `test_lagged_signal_never_equals_the_same_day_raw_value`.

Now restore:

```bash
git checkout src/forecasting_engine/ingest/align.py
uv run pytest tests/unit/test_no_leakage.py -q
```

Expected: `7 passed`

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_no_leakage.py
git commit -m "test: structural guards against look-ahead bias"
git push origin phase-0-ingestion
```

---

### Task 9: RunConfig

**Files:**
- Create: `src/forecasting_engine/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_config.py`:

```python
from dataclasses import FrozenInstanceError

import pytest

from forecasting_engine.config import DataSpec, FeatureSpec, ModelSpec, RunConfig, SplitSpec

DATA = DataSpec(path="data/raw/signals.csv", sha256="d" * 64)


def test_defaults_match_the_spec_assumptions():
    config = RunConfig(data=DATA)
    assert config.features.horizon_days == 5
    assert config.features.lag_days == 1
    assert config.split.embargo_days == 6  # horizon + 1
    assert config.seed == 42


def test_identical_configs_share_a_run_id():
    assert RunConfig(data=DATA).run_id == RunConfig(data=DATA).run_id


def test_changing_the_seed_changes_the_run_id():
    assert RunConfig(data=DATA).run_id != RunConfig(data=DATA, seed=43).run_id


def test_changing_the_data_hash_changes_the_run_id():
    other = DataSpec(path="data/raw/signals.csv", sha256="e" * 64)
    assert RunConfig(data=DATA).run_id != RunConfig(data=other).run_id


def test_changing_the_model_degree_changes_the_run_id():
    a = RunConfig(data=DATA, model=ModelSpec(degree=3))
    b = RunConfig(data=DATA, model=ModelSpec(degree=5))
    assert a.run_id != b.run_id


def test_run_id_is_a_short_hex_string():
    run_id = RunConfig(data=DATA).run_id
    assert len(run_id) == 16
    assert all(character in "0123456789abcdef" for character in run_id)


def test_config_is_immutable():
    config = RunConfig(data=DATA)
    with pytest.raises(FrozenInstanceError):
        config.seed = 1


def test_embargo_shorter_than_the_horizon_is_rejected():
    with pytest.raises(ValueError, match="embargo"):
        RunConfig(
            data=DATA,
            features=FeatureSpec(horizon_days=5),
            split=SplitSpec(embargo_days=2),
        )


def test_portfolio_defaults_to_a_benchmark_comparison():
    assert RunConfig(data=DATA).portfolio.benchmark == "equal_weight"


def test_model_params_are_hashable():
    config = RunConfig(data=DATA, model=ModelSpec(params=(("alpha", 0.1),)))
    assert config.run_id
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'forecasting_engine.config'`

- [ ] **Step 3: Write the implementation**

`src/forecasting_engine/config.py`:

```python
"""Everything needed to reproduce a run, in one frozen object.

The content hash of a RunConfig is the run id. Same config in, same numbers out
— which makes both the DuckDB run history and the result cache trivial.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class DataSpec:
    """Which file, identified by content rather than path alone."""

    path: str
    sha256: str
    start: str | None = None
    end: str | None = None


@dataclass(frozen=True)
class FeatureSpec:
    """How raw data becomes a FeaturePanel, and which signals survive screening.

    Defaults follow the working assumptions in the architecture spec: a five-day
    forecast horizon with a one-day observation lag.
    """

    horizon_days: int = 5
    lag_days: int = 1
    ffill_limit: int = 5
    screen: str = "rank_ic"
    top_k: int = 5


@dataclass(frozen=True)
class ModelSpec:
    kind: str = "derived_polynomial"
    degree: int = 3
    params: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class SplitSpec:
    """Walk-forward geometry. The embargo must cover the label window."""

    train_days: int = 756
    test_days: int = 63
    embargo_days: int = 6


@dataclass(frozen=True)
class PortfolioSpec:
    objective: str = "max_sharpe"
    benchmark: str = "equal_weight"


@dataclass(frozen=True)
class RunConfig:
    data: DataSpec
    features: FeatureSpec = field(default_factory=FeatureSpec)
    model: ModelSpec = field(default_factory=ModelSpec)
    split: SplitSpec = field(default_factory=SplitSpec)
    portfolio: PortfolioSpec = field(default_factory=PortfolioSpec)
    seed: int = 42

    def __post_init__(self) -> None:
        if self.split.embargo_days <= self.features.horizon_days:
            raise ValueError(
                f"embargo_days ({self.split.embargo_days}) must exceed horizon_days "
                f"({self.features.horizon_days}); overlapping label windows leak across the split"
            )

    @property
    def run_id(self) -> str:
        """A stable 16-character identity for this exact configuration."""
        payload = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add src/forecasting_engine/config.py tests/unit/test_config.py
git commit -m "feat: RunConfig with content-hash run identity"
git push origin phase-0-ingestion
```

---

### Task 10: End-to-end integration and README

Proves the pieces compose, and gives a new teammate a working first hour.

**Files:**
- Create: `tests/integration/test_ingest_pipeline.py`
- Modify: `README.md` (currently a single line — replace it entirely)

- [ ] **Step 1: Write the failing integration test**

`tests/integration/test_ingest_pipeline.py`:

```python
"""CSV on disk to FeaturePanel, using the same path a user takes."""

import pandas as pd
import pytest

from forecasting_engine import fixtures
from forecasting_engine.config import DataSpec, RunConfig
from forecasting_engine.ingest.align import align_and_lag
from forecasting_engine.ingest.loader import load


@pytest.fixture
def signals_csv(tmp_path):
    path = tmp_path / "signals.csv"
    fixtures.main(["--years", "5", "--seed", "11", "--out", str(path)])
    return path


def test_full_ingest_produces_a_usable_panel(signals_csv):
    panel = align_and_lag(load(signals_csv))

    assert len(panel) > 1000
    assert panel.lag_days == 1
    assert panel.targets == ("spx_fwd_5d", "agg_fwd_5d")
    assert not panel.frame.isna().any().any()
    assert panel.frame.index.is_monotonic_increasing


def test_defects_are_reported_but_do_not_block(signals_csv):
    raw = load(signals_csv)
    assert raw.issues, "the fixture generator should have injected detectable defects"
    assert align_and_lag(raw) is not None


def test_matrix_is_ready_for_a_model(signals_csv):
    panel = align_and_lag(load(signals_csv))
    features, target = panel.matrix(panel.frame.index)

    assert list(features.columns) == list(panel.signals)
    assert len(features) == len(target)
    assert features.notna().all().all()


def test_the_pipeline_is_reproducible(signals_csv):
    first = align_and_lag(load(signals_csv))
    second = align_and_lag(load(signals_csv))
    pd.testing.assert_frame_equal(first.frame, second.frame)


def test_a_run_config_can_be_built_from_a_loaded_file(signals_csv):
    raw = load(signals_csv)
    config = RunConfig(data=DataSpec(path=raw.source.path, sha256=raw.source.sha256))
    assert config.run_id
    assert config.features.horizon_days == align_and_lag(raw).horizon_days
```

- [ ] **Step 2: Run it**

```bash
uv run pytest tests/integration/ -v
```

Expected: `5 passed`. If `test_full_ingest_produces_a_usable_panel` fails on the row count, check that five years of business days minus the lag and horizon rows exceeds 1000 — it should be roughly 1250.

- [ ] **Step 3: Replace the README**

```markdown
# Forecasting Engine for Strategic Asset Allocation

Built for Alpha Norm by Team Finlytics (IS484, SMU School of Computing and
Information Systems).

Short-horizon return forecasts for equity and bond indices, validated against
overfitting, fed into portfolio construction and tail-risk reporting.

## Getting started

```bash
git clone https://github.com/raphaelkwek/forecasting-engine.git
cd forecasting-engine
uv sync --all-extras
uv run pytest
```

A green test run on a fresh clone means your environment is correct. If it is
red, that is a bug on `main` — report it rather than working around it.

You do not need real market data to start. Generate a synthetic file that
matches the specification exactly:

```bash
uv run python -m forecasting_engine.fixtures --years 10
```

This writes `data/raw/signals.csv` with deliberate duplicates, a date gap,
missing cells and a crash window, so the quality checks have something to catch.
Add `--clean` for a defect-free file.

## First look at the data

```python
from forecasting_engine.ingest.align import align_and_lag
from forecasting_engine.ingest.loader import load

panel = align_and_lag(load("data/raw/signals.csv"))
features, target = panel.matrix(panel.frame.index)
```

`panel` is lag-safe by construction: a row dated `t` holds signals observed at
`t-1` and the return realised between `t` and `t+5`.

## How this is put together

Read [docs/architecture.html](docs/architecture.html) — it covers the pipeline,
the three contracts that hold the system together, who owns what, and how to add
a model. The full design rationale is in
[docs/superpowers/specs/](docs/superpowers/specs/).

The input file contract is [docs/data-specification.md](docs/data-specification.md).

## Layout

| Path | Contains |
|---|---|
| `src/forecasting_engine/` | Everything that computes. Never imports Streamlit. |
| `app/` | Streamlit dashboard. Holds no maths. |
| `notebooks/` | Research. Imports from `src/`, never the reverse. |
| `tests/` | Unit, integration, and the look-ahead guards. |
| `docs/` | Specification, architecture, plans. |

## Working agreements

- A cell that produced a *finding* stays in the notebook. A cell that produced a
  *capability* moves into `src/` with a test.
- Backward-fill and interpolation are prohibited anywhere in `src/`; a test
  enforces this.
- `FeaturePanel` is constructed only by `align_and_lag()`; a test enforces this too.
```

- [ ] **Step 4: Run the whole suite and the linter**

```bash
uv run ruff check .
uv run pytest -v
```

Expected: `All checks passed!` and `71 passed` — 9 schema, 7 fixtures, 8 loader, 12 panel, 12 align, 7 leakage, 10 config, 5 integration, 1 smoke.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/ README.md
git commit -m "test: end-to-end ingestion pipeline; docs: README for new contributors"
git push origin phase-0-ingestion
```

---

## Definition of done for Phase 0

- [ ] `uv sync --all-extras && uv run pytest` is green on a fresh clone
- [ ] CI passes on `main`
- [ ] `uv run python -m forecasting_engine.fixtures` writes a usable file
- [ ] `docs/data-specification.md` is written and can be sent to the sponsor
- [ ] `FeaturePanel` is frozen — Joash can build against it without further changes
- [ ] The look-ahead guards fail when the lag is deliberately removed

## What Phase 0 deliberately excludes

Deferred to Sprint 1 and later, and listed so nobody builds them early:
`quality.py` and the QualityReport, univariate signal screening, the Fama-French
benchmark, `PurgedWalkForward`, every model, portfolio optimisation, risk
metrics, scenario shocks, DuckDB persistence, and the Streamlit app.

## Questions to close before Sprint 1

The four open questions in the architecture spec are running on working
assumptions. `FeatureSpec.horizon_days` and `SplitSpec.embargo_days` make Q2 a
config change rather than a rewrite, but the data specification cannot be sent
to the sponsor as final until Q1 (bond index) and Q2 (horizon) are answered.
