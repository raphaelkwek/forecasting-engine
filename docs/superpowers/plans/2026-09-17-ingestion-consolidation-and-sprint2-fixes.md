# Ingestion Consolidation & Sprint 2 Fixes — Build Spec

**Status:** Ready for implementation. **Date:** 17 Sep 2026.

**Goal:** Fix the ingestion-side issues found by walking the codebase against the
sponsor-approved proposal and validation-metrics documents (accept both CSV and
XLSX, auto-apply forward-fill within a configurable cap, remove the misleading
static signal-screening view, make the app aware of which target — equity or
bond — it's working with), then finish the remaining Sprint 2 display polish.
Every deletion goes through a verification gate before it happens — nothing is
removed on the assumption that it's dead.

**Architecture:** No new dependencies (`openpyxl` is already in `pyproject.toml`).
Work inside the existing package layout (`src/forecasting_engine/{extraction,
ingest, features, models, validation, reporting, store}`, `app/`). Read Section 0
in full before starting anything.

**Tech Stack:** Python, pandas, Streamlit, pytest, ruff. `uv run pytest`,
`uv run ruff check .` — run both before and after every phase.

---

## 0. Read this first — ground rules

- **This plan is self-contained.** It was produced by comparing the current
  codebase against two sponsor-approved documents that live outside this repo
  (the IS484 project proposal and the Validation Metrics and Framework v2, both
  `.docx`, not committed here). The facts from them that matter for this work
  are restated in Section 1 below in plain language. Do not assume you have
  access to the original files — work from this document.
- **Verify before deleting, every time.** For any file or function this plan
  marks as a removal candidate: grep the *entire* repo (`src/`, `app/`,
  `tests/`, `docs/`) for every reference to it, including string/dynamic
  imports, run the full test suite before touching anything, do the removal,
  then run the full test suite again. If a grep turns up something unexpected,
  stop and report it rather than deleting through it. Summarize what was
  removed and how the test count changed — don't delete silently.
- **Three things are explicitly blocked in this plan — do not touch them:**
  1. The outlier-detection threshold (`MAD_THRESHOLD = 8.0` in
     `extraction/validation.py`, and the equivalent in `quality/outliers.py`).
     The team's own calibration and a later, written sponsor note ("outlier SD
     > 3") disagree, and this needs a sponsor conversation before any number
     changes. Once that happens, the Validation Metrics document will need a
     matching update — that's outside this repo.
  2. The signal-screening inclusion threshold (`INCLUSION_THRESHOLD = 0.02` in
     `features/screening.py`) — still an unconfirmed working default, leave it.
  3. PBO's method and configuration (`validation/pbo.py`) — verified against
     the validation-metrics document and already correct (CSCV, matches the
     documented gate). No change needed anywhere in PBO.
- **Jira may be stale relative to the code.** As of the last export, several
  Module 2 subtasks (Fama-French, Polynomial, ML plumbing) show "To Do"/"To
  Review," but `main` already has all three model families fitting through the
  shared walk-forward harness with IC/OOS Rank IC/RMSE/PBO/crash diagnostics.
  Trust the code over the tracker for "is this built"; flag mismatches back to
  the team rather than re-doing finished work or trusting a stale status.

---

## 1. Context: what's confirmed, what changed this sprint, what's still open

- **Sponsor:** Dr. Catalin Burlacu, Alpha Norm. Product owner side: Toby Chan.
- **Targets, confirmed:** S&P 500 (equity) and the Bloomberg/Barclays Agg bond
  index (bond), both on a **total-return basis** (dividends/coupons
  reinvested) — not the plain price series. Every metric is computed **per
  target, never pooled** across the two.
- **Data ingestion — reopened this sprint.** The proposal originally locked
  ingestion to "structured CSV upload," confirmed by the sponsor. That
  confirmation rested on the sponsor's own belief that Bloomberg terminal
  exports CSV directly. The team has since established this may not be true —
  Bloomberg may only produce Excel (`.xlsx`) exports, with CSV only reachable
  via a manual "Save As" in Excel. **Decision: support both `.csv` and
  `.xlsx` uploads** rather than resolve which one Bloomberg "really" gives.
  The proposal's scope boundary should eventually be updated to reflect this,
  but that's a documentation change for the team, not part of this plan.
- **Schema — decided this sprint: stays open/dynamic.** Do not lock ingestion
  to the fixed 8-signal contract that already exists in `ingest/schema.py`
  (`spx_close`, `agg_close`, `vix`, `credit_spread_hy`, `credit_spread_ig`,
  `fx_impl_vol`, `breakeven_10y`, `term_spread`, plus `date`). Any numeric
  column the uploader produces should be accepted and screened generically —
  which is what the currently-live `extraction/` pipeline already does. This
  decision is *why* several older, fixed-contract modules become removal
  candidates in Phase 3 — but each one still goes through the verification
  gate above, and a couple of pieces inside them (the ticker→role mapping, the
  per-signal calendar logic) are worth keeping even though the module they
  live in isn't.
- **Outlier detection — unresolved, blocked (see Section 0).**
- **Crash recall and PBO — verified correct, no changes anywhere in this plan.**
  Crash recall's exact definition (flagged when predicted return is below the
  5th percentile of that model's own training-window predictions; a true tail
  day is a realised return below −2 SD of the training-window return
  distribution) matches the validation-metrics document precisely.

---

## Phase 1 — Ingestion: accept both CSV and XLSX on the open schema

**Goal:** the Data page accepts either format for a Bloomberg export, both
merging into the same shape the rest of the pipeline already consumes.

### Task 1.1 — an xlsx reader for the freeform (open-schema) pipeline

- [ ] Add an xlsx reader alongside `extraction/bloomberg_csv.py` (e.g.
      `extraction/bloomberg_xlsx.py`) that produces the same
      `BloombergCsvExport`-shaped result (`filename`, `security`, `frame` with
      `Date` + `{label}_{field}` columns) — not the fixed-contract shape
      `ingest/bloomberg.py` currently produces, since we've decided to stay
      open-schema.
- [ ] Don't write the xlsx-parsing logic from scratch: `ingest/bloomberg.py`
      already has a tested `openpyxl`-based reader (`read_export`, reading the
      `Data`/`Metadata` sheets, security detection, `dedupe_dates`). Reuse or
      adapt its internals rather than duplicating them. Whether that means
      importing from `ingest/bloomberg.py` with a thin adapter, or moving the
      shared parsing logic somewhere both pipelines can use, is an
      implementation judgment call — minimize duplication, and resolve Phase
      3's question about `ingest/bloomberg.py`'s fate only after this is done.
- [ ] `openpyxl` is already a dependency (`pyproject.toml`) — nothing to add.
- [ ] Unit tests mirroring `tests/unit/test_extraction_bloomberg_csv.py`'s
      structure for the new reader.

### Task 1.2 — wire both formats into the upload UI

- [ ] `ingest/upload.py::check_extension()` currently only accepts `.csv`
      (raises `FileTypeError` otherwise, line ~81-87) — extend to accept
      `.xlsx` too.
- [ ] `app/bloomberg_extraction_panel.py`'s per-file loop (around line 92-114)
      always calls `bloomberg_csv.read_export()` today — branch on file
      extension and call the new xlsx reader for `.xlsx` files. Both readers
      must return the same shape so `merge()` needs no changes.
- [ ] Update the uploader's caption/help text and `docs/bloomberg-exports.md`
      to describe both accepted formats.
- [ ] Extend `tests/functional/test_bloomberg_extraction_page.py` to cover an
      xlsx upload end to end.

---

## Phase 2 — Forward-fill: apply automatically, cap-limited, surface only what's left over

**Files:** `src/forecasting_engine/extraction/bloomberg_csv.py`,
`app/bloomberg_extraction_panel.py`

**Current behaviour:** `_render_gap_review()` lists every row with any missing
value in an editable table, defaulting every row to "include" — i.e. *not*
filled — regardless of whether the reason is a weekend, a market holiday, or a
genuinely unexplained gap. A person has to manually tick a row, or click
"Clean all," before anything gets forward-filled.

**New behaviour:**

- [ ] Forward-fill every missing cell automatically, per column, up to a
      configurable max-gap-days cap — no manual per-row action required, and
      regardless of the reason label. `forward_fill()`'s underlying mechanic
      (`ffill(limit=max_gap)`) is already correct; what changes is *when* it
      runs (always, not only on rows a person marked) and what the review UI
      shows.
- [ ] Keep the max-gap-days control configurable — this is a Tier 0 CTQ
      requirement in the validation-metrics document ("forward-fill only,
      within the configured limit"), not something to hardcode.
- [ ] After auto-filling, only show a review row for a date that **still**
      has a missing value once the cap has been applied (i.e. the gap
      exceeded `max_gap`). A gap the fill already resolved needs no human
      judgement and shouldn't appear in the review table at all.
- [ ] `missing_row_report()`'s gap-reason labelling currently checks every
      column against one blanket NYSE calendar (`_HOLIDAY_CALENDAR = "NYSE"`,
      line ~34), which is known to be less accurate than a per-signal
      calendar (`quality/gaps.py` already does this correctly but is
      currently unused — see Phase 3). Porting that logic in is optional for
      this phase; the reason label is informational and doesn't currently
      gate what gets filled. Decide in Phase 3 whether to do it.
- [ ] Remove the now-unnecessary manual per-row decision state
      (`gap_decisions_*` session-state keys, the checkbox column, "Clean
      all"/"Include all" buttons) if the redesign no longer needs them —
      through the verification gate in Section 0.
- [ ] Update tests around `forward_fill`/`missing_row_report` and the
      functional Data-page test to assert: gaps fill without manual
      interaction, and a gap longer than `max_gap` still shows up as
      unresolved.

---

## Phase 3 — Ingestion pipeline cleanup (verify, then remove)

Because schema stays open/dynamic (Section 1), the following are removal
**candidates** — every one still goes through Section 0's verification gate
first, and a couple have pieces worth keeping even if the surrounding module
goes:

- [ ] `src/forecasting_engine/ingest/schema.py` and `ingest/validation.py` —
      the fixed 8-column contract and its validator. Superseded by the
      open-schema decision.
- [ ] `src/forecasting_engine/quality/` (all of it: `report.py`,
      `schema_check.py`, `outliers.py`, `gaps.py`, `missing.py`, `build.py`) —
      confirmed via repo-wide grep to have zero callers outside its own tests
      as of this plan. Two things worth salvaging before deleting the package:
      1. `quality/gaps.py`'s per-signal market-calendar logic is more
         accurate than the live blanket-NYSE approach — consider porting it
         into Phase 2's gap-reason labelling rather than discarding it.
      2. `quality/outliers.py`'s MAD implementation duplicates
         `extraction/validation.py`'s (`_robust_z`/`_drop_rebounds`) —
         once one is confirmed the single source of truth, the other goes.
- [ ] `src/forecasting_engine/store/validations.py` — a DuckDB event-log table
      never written to by the live app (only `store/uploads.py` is used).
      Confirm no other caller before removing.
- [ ] `src/forecasting_engine/ingest/bloomberg.py`, `ingest/workbook.py`, and
      the `convert.py` CLI — the `.xlsx`-to-fixed-contract converter. Its fate
      depends on how Task 1.1 was implemented: if Phase 1 built a genuinely
      new xlsx reader inside `extraction/`, this becomes redundant; if Phase 1
      adapted/reused this module directly, it survives as a real dependency.
      Resolve only after Phase 1 is done. **Do not delete `TICKER_MAP`
      wholesale** even if the fixed-contract converter around it goes — it's
      needed for target identification in Phase 4.
- [ ] `extraction/workbook.py` vs. `ingest/workbook.py` — functionally
      identical `.xlsx`-writer modules (only the sheet-name constant
      differs). Keep one; have the other re-export it, or delete the
      redundant one — whichever is simpler once Phase 1 settles.

**Do not remove:** `ingest/align.py`, `ingest/fama_french.py`,
`ingest/provenance.py`, `ingest/upload.py`'s file-level checks
(`check_extension`, `check_size`, `accept_upload`) — all confirmed live.

---

## Phase 4 — Target identification and model/target awareness

**Files:** `app/app_pages/4_Models.py`, `app/app_pages/3_Model_Metrics.py`,
`app/app_pages/2_Signals.py` (until Phase 5 removes it), a shared location for
the ticker→role mapping (inside `extraction/` or a small new module).

### Task 4.1 — identify the two targets by ticker, not by merged column name

- [ ] Both the Signals and Models pages currently offer a plain
      `st.selectbox` over every numeric column in the merged frame as
      "target" — those column names are filename-derived and not stable
      (confirmed: two real uploaded files produced a target column name
      driven entirely by the uploaded filename, not by anything guaranteed to
      repeat). Replace this with a mapping from **Bloomberg Security ticker**
      (the same metadata field `extraction/bloomberg_csv.py::_security()`
      already extracts) to a fixed role — equity vs. bond. `ingest/
      bloomberg.py::TICKER_MAP` already has this pattern
      (`"SPX Index" → spx_close`, etc.) — reuse the concept even if that
      module is otherwise retired in Phase 3. Confirm the exact ticker string
      the team's real AGG export uses before hardcoding it — don't guess.
- [ ] Match on the **total-return field** specifically
      (`TOT_RETURN_INDEX_GROSS_DVDS` or equivalent), per the validation-
      metrics document's total-return-basis requirement — not the plain price
      series.
- [ ] Target selection becomes two fixed choices ("Equity — S&P 500 total
      return" / "Bond — AGG total return"), resolved internally to whichever
      uploaded column actually matches that ticker + field — not a free
      column-name picker.
- [ ] If a required target ticker isn't present in the current upload, show a
      clear error rather than silently letting the user pick something else.

### Task 4.2 — namespace results by target; disable invalid combinations

- [ ] `POLYNOMIAL_RESULT_KEY` etc. in `4_Models.py` (and the duplicated
      constants in `3_Model_Metrics.py`) are keyed only by model family today
      — running the same family against a different target silently
      overwrites the other target's stored result. Add the target to the key
      (or have `ModelRunResult` carry its target, and have Model Metrics
      group/display per target instead of one flat table).
- [ ] Fama-French 5-Factor is an equity-only benchmark and is not designed to
      predict bond returns, even though it will run and produce numbers if
      asked to. Disable or hide that model-family option when the bond target
      is selected.
- [ ] Extend functional/AppTest coverage to assert: FF5 is unavailable for
      the bond target, and switching targets doesn't clobber the other
      target's stored result.

---

## Phase 5 — Remove the static Signal Screening tab; add per-fold inclusion visibility

**Files:** `app/app_pages/2_Signals.py` (delete), `app/Home.py` (remove from
navigation), `app/app_pages/4_Models.py` (add the replacement view)

- [ ] Delete `app/app_pages/2_Signals.py` and its entry in `app/Home.py`'s
      `st.navigation`. Rationale: it runs one full-history rank-IC screen
      with no train/test split — a different, more optimistic computation
      than the per-fold screening the harness actually performs for ML and
      Derived-Polynomial — and showing both, unlabelled, misleads a reader
      into thinking they're the same number.
- [ ] `src/forecasting_engine/features/screening.py` is **not** dead —
      `screen_over_folds()` is actively used by
      `validation/harness.py::evaluate(..., screen=True)`. Only the page
      goes, not the module.
- [ ] Add, next to the existing fitted-terms/SHAP table on the Models page
      (meaningful only when `screen=True` is used, i.e. ML and Derived-
      Polynomial): a small table of each signal against how many of the
      walk-forward folds included it (e.g. "vix: 8/8", "fx_impl_vol: 0/8").
      This needs `evaluate()` (or `run_boosted()`/`run_derived_polynomial()`)
      to expose the per-fold screening result instead of discarding it after
      fitting — decide whether that's a new `FoldResult` field or a separate
      call to `screen_over_folds()` run alongside the existing `evaluate()`
      call.
- [ ] Retire test coverage specific to the deleted page; add coverage for the
      new per-fold inclusion summary.

---

## Phase 6 — Remaining Sprint 2 display polish (after Phases 1–5)

Verify current status in code before starting each — Jira may be stale
(Section 0). These don't depend on the ingestion work above:

- [ ] Render the fitted polynomial in readable mathematical notation (term,
      exponent, coefficient) instead of the current raw terms/coefficients
      dataframe.
- [ ] Map internal signal codes to plain-language labels (e.g. `vix` → "CBOE
      Volatility Index") in the Models/Model Metrics display; round displayed
      coefficients to an agreed number of significant digits — confirm the
      digit count with the team, it isn't specified anywhere reviewed so far.
- [ ] Label a shown polynomial as "User-Supplied" vs. "Derived," and
      auto-refresh the display when a new one is derived or uploaded.

---

## Out of scope for this plan

- Any change to the outlier-detection threshold (blocked on sponsor input).
- Any change to the signal-screening inclusion threshold or PBO's method/config.
- Module 3 (Portfolio Evaluation) and the scenario/risk parts of Module 4 —
  nothing exists for these yet anywhere in the codebase; needs its own plan.
- Role-based access control — explicitly out of scope per the proposal.

---

## Definition of done, per phase

- `uv run pytest` passes.
- `uv run ruff check .` passes.
- For any removal: a short before/after note (files removed, test count
  before → after) rather than a silent deletion.
- Manually exercise the affected Streamlit page(s) and confirm behaviour
  matches this spec before moving to the next phase — don't chain phases on
  an unverified previous one.
