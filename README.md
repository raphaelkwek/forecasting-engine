# Forecasting Engine

Forecasts short-horizon returns for liquid equity and bond indices, validates
those forecasts against overfitting, feeds them into portfolio construction, and
reports tail risk. Built for Alpha Norm by Finlytics (IS484).

## Getting started

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). On macOS:
`brew install uv`.

```bash
uv sync --all-extras
```

Then run the dashboard:

```bash
uv run streamlit run app/Home.py
```

It opens at <http://localhost:8501>. Go to the **Data** page and upload a signal
CSV — see [docs/data-specification.md](docs/data-specification.md) for the
column contract, the 25 MB size limit, and which placeholder tokens count as
blank.

Coming from Bloomberg? Its exports are one workbook per security, not one CSV.
Convert them first:

```bash
uv run python -m forecasting_engine.convert ~/Documents/FYP/exports/*.xlsx -o data/signals.csv
```

Substitute your own export folder — the shell expands the `*.xlsx`, so
`no matches found` means that path holds no workbooks. See
[docs/bloomberg-exports.md](docs/bloomberg-exports.md) for which securities to
pull.

## Checks

```bash
uv run pytest
```

```bash
uv run ruff check .
```

Both run in CI on every pull request.

## What works today

The left edge of the pipeline: upload and validation.

- **Upload** — file type, size and CSV parsing, with the file stored under its
  content hash and the event logged to DuckDB.
- **Schema validation** — required columns, per-column types and ranges,
  reporting the column, line number and date of each problem. Blocking faults
  halt the pipeline; range breaches are reported and retained.
- **Outlier detection** — flags extreme daily moves per signal, retains every
  value, and lets the portfolio manager include or exclude each one.
- **Gap reconciliation** — checks missing dates against each signal's own market
  calendar, so holidays and weekends are not reported as missing data.
- **Data quality report** — on the dashboard's front page: date range,
  per-signal completeness, and every flagged observation, expandable by signal.
- **Synthetic data** — a generator producing contract-shaped files with known
  defects, so the pipeline can be run before real exports arrive.

Forecasting, portfolio construction and risk analysis are not built yet.

## Layout

```
src/forecasting_engine/     core library, never imports Streamlit
  ingest/                   upload, schema, validation
  quality/                  the shared data quality report
  store/                    DuckDB history
app/                        Streamlit dashboard, no maths
docs/                       data specification, design, decisions
tests/                      unit, integration, functional
```

## Documentation

- [Data specification](docs/data-specification.md) — the CSV contract
- [Bloomberg exports](docs/bloomberg-exports.md) — which securities to pull, and
  the converter that joins them
- [Quality report contract](docs/quality-report-contract.md) — cross-ticket
  design decisions for the shared report model
- [Outlier detection](docs/outlier-detection.md) — the method, its calibration
  against real data, and the evidence for each choice
- [Market calendars](docs/market-calendars.md) — the calendar source, the
  per-signal mapping, and how gaps are reconciled against it
- [Architecture design](docs/superpowers/specs/2026-07-29-forecasting-engine-architecture-design.md)
- [Phase 0 plan](docs/superpowers/plans/2026-07-29-phase-0-scaffold-and-ingestion.md)
