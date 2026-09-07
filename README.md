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

It opens at <http://localhost:8501>. Go to the **Data** page. There are two
ways in:

- **A signal CSV** already in the contract's shape — see
  [docs/data-specification.md](docs/data-specification.md) for the column
  contract, the 25 MB size limit, and which placeholder tokens count as blank.
- **Bloomberg exports** — the terminal's own CSV history exports, one per
  security. Drop them all in at once; the page joins them on date, maps each
  security onto its contract column, and hands the result to the same
  validation. See [docs/bloomberg-exports.md](docs/bloomberg-exports.md) for
  which securities to pull.

Workbook (`.xlsx`) exports have a command-line converter that does the same
join:

```bash
uv run python -m forecasting_engine.convert ~/Documents/FYP/exports/*.xlsx -o data/signals.csv
```

Substitute your own export folder — the shell expands the `*.xlsx`, so
`no matches found` means that path holds no workbooks. Or save the workbooks
as CSV and use the Data page.

## Checks

```bash
uv run pytest
```

```bash
uv run ruff check .
```

Both run in CI on every pull request.

## What works today

The left edge of the pipeline: getting data in, and checking it.

- **Upload** — file type, size and CSV parsing, with the file stored under its
  content hash and the event logged to DuckDB.
- **Bloomberg merge** — any number of Bloomberg CSV exports joined on date and
  mapped onto the contract in the app, with the wrong-ticker mistakes named
  (`LF98TRUU` for `LF98OAS`, `JPMVXYGL` for `JPMVXYG7`). The merged file is an
  upload like any other.
- **Fama-French factors** — Ken French's daily five-factor file, downloaded on
  request and kept under its content hash for the FF5 benchmark.
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

## Interface

The dashboard uses a trading-terminal palette: a dark canvas with an orange
accent and gold for the brand mark, and a light counterpart with the same
bones. Semantic green, amber and red are reserved for state and never share a
hue with the accent, so a "blocking" badge is never mistaken for decoration.
Both themes are defined explicitly in `.streamlit/config.toml`, and the page
follows whichever the viewer has active. The stylesheet and the animated
background live in `app/assets/`.

Status appears as a lozenge — a short uppercase badge — rather than a coloured
word or a symbol, because it reads at a glance in a list. `app/ui.py` holds that
and the shared presentation helpers.

No emoji anywhere: an internal analytical tool should read as a tool.

## Layout

```
src/forecasting_engine/     core library, never imports Streamlit
  ingest/                   upload, schema, validation, the Bloomberg readers,
                            Fama-French
  quality/                  the shared data quality report
  store/                    DuckDB history
app/                        Streamlit dashboard, no maths
  ui.py                     lozenges, status rows, shared presentation
  assets/                   stylesheet and animated background
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
- [Ingestion consolidation](docs/ingestion-consolidation.md) — why there is one
  validator, one outlier method, one calendar approach and one converter, and
  the evidence behind each
- [Architecture design](docs/superpowers/specs/2026-07-29-forecasting-engine-architecture-design.md)
- [Phase 0 plan](docs/superpowers/plans/2026-07-29-phase-0-scaffold-and-ingestion.md)
