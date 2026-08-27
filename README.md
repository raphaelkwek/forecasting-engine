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