# Ingestion Consolidation & Sprint 2 Fixes — Build Spec

**Status:** In progress. Everything is done except Phase 6 (display polish,
itself mostly superseded by a separate ticket — see the progress log at the
bottom). **Date:** 17 Sep 2026.

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

## Review corrections — read before the phases (17 Sep, checked against the code)

The plan was checked claim by claim against `Toby`. The code facts it states
are accurate. Five things needed correcting, and the build order below replaces
the phase numbering.

**1. A live target-horizon bug, now fixed (`9bbf9a0`).** Not in the original
plan. `align_and_lag` built the target with `pct_change(horizon)` on the merged
frame, counting rows. The merged frame has a row for every date *any* series
traded, so a day the target's market was shut is a row with no price. A
"5-day" label crossing it was really a 4-day return, and the real move across
it was dropped. On the real SPX + Global Aggregate exports: **347 of 2,422
five-day SPX labels (14.3%) were the wrong horizon, and 173 real labels were
dropped.** Both are now zero. `PurgedWalkForward` had to change with it — it
purged by counting rows, which let a label that skips a closed day keep a price
from inside the test window (the `2e768a3` leak, reopened). It now also purges
on `FeaturePanel.label_end`. Crash recall and PBO needed no change themselves,
but their inputs were affected.

**2. Phase 2 must forward-fill signal columns only, never targets.** As written
it fills every column. A filled target price on a closed day reads as a real
trading day and becomes a fabricated 0% return — and it silently undoes fix 1.
Phase 2 can't tell targets from signals until Phase 4.1 separates the uploads,
so **4.1 now comes before 2**.

**3. Phase 3's dependency list was incomplete.** Found by the verification gate:
- `ingest/bloomberg_csv.py` is not listed, but it is dead (only its own test
  imports it) and it imports `ingest/bloomberg.py`, so they go together.
- `fixtures.py` and `tests/unit/test_fixtures.py` import `ingest/schema.py`.
  Deleting `schema.py` breaks the synthetic data generator.
- `quality/` is not caller-free: `tests/integration/test_polynomial_flow.py`
  and `test_screening_flow.py` — live modelling tests — call
  `apply_decisions()`. Both calls pass an empty report, so they are no-ops and
  can simply be removed.

**4. The bond target is `LBUSTRUU` (US Aggregate), decided 17 Sep.** The plan
says "Barclays Agg", which is the US index, but the team's real export was
`LEGATRUU`, the *Global* Aggregate — a different index and calendar. Recorded in
`docs/bloomberg-exports.md` under "Target indices". Phase 4.1's detection
defaults to `LBUSTRUU`; the existing `LEGATRUU` exports need re-pulling.

**5. `TICKER_MAP` needs reshaping, not relocating.** It maps ticker → fixed
column name (`"SPX Index": "spx_close"`). Phase 4.1 needs ticker → target role
(equity or bond). Only 2 of its 7 entries are targets; the rest are signals,
which the open schema doesn't map at all.

**Build order:** 3 → 5 → 4.3 → 4.1 → 2 → 4.2 → 6. Phases 3, 5 and 4.3 are
independent of the ingestion redesign; 4.1 must precede 2 (correction 2); 4.2
reads what 4.1 commits.

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

### Task 1.1 — an xlsx reader for the freeform (open-schema) pipeline — DONE

- [x] Added `extraction/bloomberg_xlsx.py`, producing the same
      `BloombergCsvExport`-shaped result (`filename`, `security`, `frame` with
      `Date` + `{label}_{field}` columns, now also `notes`) — not the
      fixed-contract shape `ingest/bloomberg.py` produced.
- [x] Ported (not imported) the three contract-independent pieces from
      `ingest/bloomberg.py`: workbook opening/corrupt-file handling,
      `_security()`, and a frame-level analog of `dedupe_dates()` (adapted to
      dedupe a whole row at once, since a workbook's `Data` sheet has every
      field for a date on one row, not one series per field). Ported directly
      into the new module rather than importing from `ingest/bloomberg.py`,
      since that module is retired in Phase 3 — importing from it first would
      have meant undoing the import later. `label()` in
      `extraction/bloomberg_csv.py` was made public (renamed from `_label`)
      so both readers share it.
- [x] Also added: numeric coercion per field column (`pd.to_numeric(...,
      errors="coerce")`) — reading raw cell values via `openpyxl` doesn't get
      `pd.read_csv()`'s automatic NA-string handling for free, so Bloomberg's
      `#N/A N/A` placeholder needed explicit handling to avoid every
      placeholder cell being reported as a schema/type error downstream.
- [x] `ingest/bloomberg.py`, `ingest/workbook.py`, `convert.py` **not yet
      deleted** — that happens in Phase 3, after `TICKER_MAP` is relocated
      for Phase 4's use.
- [x] `openpyxl` already a dependency — nothing added.
- [x] `tests/unit/test_extraction_bloomberg_xlsx.py` — 8 tests: security from
      metadata not filename, every field kept (not just one), placeholder →
      NaN, missing Data sheet refused, missing Metadata tolerated, repeated
      date deduped with a note, dates parsed as real datetimes, a non-zip
      file refused without crashing.

### Task 1.2 — wire both formats into the upload UI — DONE

- [x] `ingest/upload.py::check_extension()` now accepts `.csv` and `.xlsx`;
      error message names both accepted extensions.
- [x] `app/bloomberg_extraction_panel.py`'s per-file loop branches on
      extension (`.xlsx` → `bloomberg_xlsx.read_export`, else
      `bloomberg_csv.read_export`); both exception types caught together.
      `st.file_uploader`'s `type` param now set to `["csv", "xlsx"]`
      (previously `None`) for the native picker/filter UI benefit.
- [x] Updated the uploader caption, the "no data yet" info messages (Data
      page and Home summary), and `docs/bloomberg-exports.md` (added an
      `.xlsx`-shape example alongside the CSV one) to describe both formats.
- [x] `tests/functional/test_bloomberg_extraction_page.py` — added
      `xlsx_export()` helper plus two tests: an all-xlsx upload merges the
      same as the equivalent CSV, and a mixed CSV+xlsx upload merges into one
      frame. Three pre-existing tests updated for now-changed copy/behavior
      (the "upload to get started" text, and two `.xlsx`-is-rejected test
      cases in `test_upload.py`/`test_upload_flow.py` that assumed `.xlsx`
      was always invalid — updated to use `.xls` instead, which is still
      correctly rejected).
- [x] Full suite green (`uv run pytest`) and `uv run ruff check .` clean
      after these changes.

### Task 1.3 — accept a previously-merged file back in, without re-labelling it (DEFERRED — do not implement yet, pending team discussion)

Motivation: `st.session_state` is wiped by any browser refresh or restart
(there is no server-side persistence today), so a user who already merged and
downloaded a Bloomberg dataset in an earlier session currently has no way to
resume from that download — re-uploading it through the existing uploader
mangles it (see below), forcing a full redo of the raw-file merge.

- [ ] `read_export()` identifies a raw per-security export by finding a
      `Date,` header line with a metadata block above it, and labels its
      columns from the `Security` value found there (or the filename, as a
      fallback). A previously-downloaded merged file has `Date` as its very
      first line with **no** metadata block above it, and its columns are
      **already** labelled (`SPX_Index_PX_LAST`, etc.) — fed through
      `read_export()` unchanged, it reads as "no security found," falls back
      to a filename-derived label, and re-prefixes every already-labelled
      column a second time, producing garbage column names. Confirmed by
      tracing the current code; do not assume this already works.
- [ ] Detect this shape (first line is the `Date,` header, no metadata block)
      and, when detected, pass the file through as the merged frame directly
      — skipping labelling and the per-file merge step — rather than routing
      it through `read_export()`/`merge()`. It should still go through
      validation and the gap-review step like any other merge result.
- [ ] Fama-French factors need no equivalent fix — `fama_french.load_latest()`
      already reads from an on-disk cache (`data/fama_french/`) independent of
      session state, so it survives a lost session on its own.
- [ ] **Considered and rejected: a second uploader on the Models page** for
      resuming a lost session. A second entry point for data would need to
      independently redo target detection and validation and write into the
      same committed session state the Data tab produces, or the two paths
      drift out of sync — the exact pattern that caused the original
      ingestion-pipeline duplication this plan is cleaning up. The Data-tab
      fix above is the only resume mechanism; do not add another one on
      `4_Models.py`.

---

## Phase 2 — Forward-fill: apply automatically, cap-limited, surface only what's left over — DONE

**Files:** `src/forecasting_engine/extraction/bloomberg_csv.py`,
`app/bloomberg_extraction_panel.py`

**Was:** `_render_gap_review()` listed every row with any missing value in an
editable table, defaulting every row to "include" — i.e. *not* filled —
regardless of reason. A person had to manually tick a row, or click "Clean
all," before anything got forward-filled, and it filled every column
including targets.

**Now:**

- [x] `forward_fill()`'s signature changed from `(frame, clean_dates,
      max_gap)` to `(frame, max_gap, *, exclude=())` — every column except
      `exclude` is filled on every row automatically, no manual selection.
      `exclude` exists specifically so a caller can pass the resolved target
      columns (Task 4.1's `COMMITTED_TARGETS_KEY`/`target_columns`) and have
      them skipped, per correction 2 — a filled target price on a closed day
      would fabricate a return that never happened and silently undo the
      Phase 1/`9bbf9a0` horizon fix.
- [x] Max-gap-days stays a configurable `number_input` on the Data page (Tier
      0 CTQ requirement) — nothing hardcoded.
- [x] `_render_gap_review()` (now effectively a summary, not a review) fills
      immediately and shows only what `missing_row_report()` still finds
      afterward — a gap that exceeded the cap, or any target-column gap
      (targets are excluded from filling at any gap length, so a target's
      calendar closures are always visible here, permanently, by design).
- [x] Per-signal calendar labelling (the optional item from the original
      plan) — **not done**, left as `quality/gaps.py`'s logic was already
      removed in Phase 3 before this phase started; porting it back in would
      mean re-adding what Phase 3 deleted. `missing_row_report()`'s blanket-
      NYSE-calendar reason labelling is unchanged. Revisit only if the reason
      text turns out to matter in practice — it's informational only, it
      doesn't gate what gets filled.
- [x] Removed: `gap_decisions_*` session-state keys, the checkbox column,
      "Clean all"/"Include all" buttons — none of it is reachable any more.
- [x] Tests: `tests/unit/test_extraction_bloomberg_csv.py` — `forward_fill`
      tests rewritten for the new signature, plus a new test confirming an
      excluded column stays untouched while others still fill.
      `tests/functional/test_bloomberg_extraction_page.py` — rewrote the two
      tests that referenced the removed buttons; added tests for a short gap
      auto-filling silently, a gap longer than the cap still showing as
      missing, auto-fill never dropping a row, and (using both uploaders
      together) a target column staying blank even for a gap short enough
      that a signal would have auto-filled it. `docs/bloomberg-exports.md`
      updated (the "gaps are left as gaps" claim was no longer true).
      Full suite green, `ruff check .` clean, verified in the browser.

---

## Phase 3 — Ingestion pipeline cleanup (verify, then remove)

Because schema stays open/dynamic (Section 1), the following are removal
**candidates** — every one still goes through Section 0's verification gate
first, and a couple have pieces worth keeping even if the surrounding module
goes:

- [x] `src/forecasting_engine/ingest/schema.py` and `ingest/validation.py` —
      the fixed 8-column contract and its validator. Superseded by the
      open-schema decision.
- [x] `src/forecasting_engine/quality/` (all of it: `report.py`,
      `schema_check.py`, `outliers.py`, `gaps.py`, `missing.py`, `build.py`) —
      confirmed via repo-wide grep to have zero callers outside its own tests
      as of this plan. Two things worth salvaging before deleting the package:
      1. `quality/gaps.py`'s per-signal market-calendar logic is more
         accurate than the live blanket-NYSE approach — consider porting it
         into Phase 2's gap-reason labelling rather than discarding it.
      2. `quality/outliers.py`'s MAD implementation duplicates
         `extraction/validation.py`'s (`_robust_z`/`_drop_rebounds`) —
         once one is confirmed the single source of truth, the other goes.
- [x] `src/forecasting_engine/store/validations.py` — a DuckDB event-log table
      never written to by the live app (only `store/uploads.py` is used).
      Confirm no other caller before removing.
- [x] `src/forecasting_engine/ingest/bloomberg.py`, `ingest/workbook.py`, and
      the `convert.py` CLI — the `.xlsx`-to-fixed-contract converter. **Decided:
      these are retired once Task 1.1 is done** — the new xlsx reader only
      reuses three small, contract-independent helpers from `bloomberg.py`
      (workbook opening, `_security()`, `dedupe_dates()`); everything else in
      these modules exists solely to serve the fixed contract. **Do not
      delete `TICKER_MAP`'s mapping table** even though the module around it
      goes — move it to wherever Phase 4's target-identification logic lives
      before deleting the rest of the file.
- [x] `extraction/workbook.py` vs. `ingest/workbook.py` — functionally
      identical `.xlsx`-writer modules (only the sheet-name constant
      differs). Keep one; have the other re-export it, or delete the
      redundant one — whichever is simpler once Phase 1 settles.

**Do not remove:** `ingest/align.py`, `ingest/fama_french.py`,
`ingest/provenance.py`, `ingest/upload.py`'s file-level checks
(`check_extension`, `check_size`, `accept_upload`) — all confirmed live.

---

## Phase 4 — Target identification, at ingestion, and model/target awareness

**Files:** `app/bloomberg_extraction_panel.py`, `app/app_pages/4_Models.py`,
`app/app_pages/3_Model_Metrics.py`, a shared location for the ticker→role
mapping (inside `extraction/` or a small new module).

Design decision (from team discussion): target selection happens **at
ingestion**, not on the Models page — this matches the proposal's own Step 1
("the user uploads... and selects the target indices"). The Models page reads
which targets were confirmed, it doesn't ask the user to pick a column.

### Task 4.1 — explicit target vs. signal uploads, with ticker detection as a pre-filled default — DONE

Design decision (from team discussion): don't rely on pure inference to
decide which uploaded files are targets (y) vs. signals (x) — a single
Bloomberg file can carry multiple fields (e.g. both `PX_LAST` and
`TOT_RETURN_INDEX_GROSS_DVDS` in one export), so even correctly identifying
"this file is SPX Index" doesn't by itself say which *column* is the target.
Make the split structural and explicit, with detection as a convenience.

- [x] Split the Data page's upload area into two: **"Target index files"**
      and **"Signal files"** (`app/bloomberg_extraction_panel.py`). Each has
      its own `st.file_uploader` and its own working-copy session keys
      (`TARGET_MERGED_KEY`/`TARGET_REPORT_KEY` vs. `SIGNAL_MERGED_KEY`/
      `SIGNAL_REPORT_KEY`), parsed/merged through a shared `_parse_and_merge()`
      helper (both uploaders need identical per-file validation, only the
      role handling afterward differs).
- [x] Ticker detection via `extraction/targets.py::TARGET_TICKERS`
      (`SPX Index` → equity, `LBUSTRUU Index` → bond, per correction 4/5 —
      Phase 3 had already salvaged and reshaped this from `TICKER_MAP`) runs
      as a pre-filled default in `_render_target_uploader()`: a `Role`
      selectbox per uploaded target file, defaulted to the detected role via
      `index=`, `None`/blank when the ticker isn't recognised — always
      overridable, never silently trusted. A parallel `Field` selectbox picks
      which column is the target series when a file carries more than one
      field.
- [x] Field defaults to `PREFERRED_FIELD = "TOT_RETURN_INDEX_GROSS_DVDS"`
      (now defined in `extraction/targets.py`) when present, else the first
      available field — overridable via the Field selectbox.
- [x] Committing with only one (or zero) targets resolved does not block
      "Use Updated Data" — `COMMITTED_TARGETS_KEY` stores whatever mapping of
      `TargetRole → column name` was actually resolved, which can be a
      partial or empty dict. Two files both resolving to the same role is
      caught and surfaced as an error (`st.error`, "pick one role per file")
      rather than silently taking the last one.
- [x] Target and signal merges combine via a new `_combine()` (outer join on
      Date) only at the point a single frame is needed downstream
      (`COMMITTED_KEY`) — signal-column candidates for modelling will draw
      only from the signal merge once Task 4.2 reads `COMMITTED_TARGETS_KEY`,
      so a target can't end up treated as a signal by construction, not by a
      runtime exclusion check.
- [x] Tests: `tests/functional/test_bloomberg_extraction_page.py` — 6 new
      tests (role pre-fill for both known tickers, an unrecognised ticker
      leaving the role unset without breaking the page, the field defaulting
      to total-return when present, the same-role-twice error, combining
      target+signal into one committed frame with the right
      `COMMITTED_TARGETS_KEY`, and committing with only one target present).
      8 pre-existing tests updated (new session-state key names, the changed
      "nothing uploaded" message) — all were about generic merge/validate
      behaviour unrelated to target roles, so they were rerouted to upload
      through the signal uploader rather than changed in substance.
      `tests/unit/test_extraction_targets.py` — 1 new test for
      `PREFERRED_FIELD`. Full suite green, `ruff check .` clean, verified in
      the browser (both upload sections render correctly, no console/server
      errors beyond Streamlit's own offline telemetry calls).

### Task 4.2 — Models page: target-aware, not target-agnostic — DONE

Implemented against the app as it actually stands now, not as this plan
originally described it — the pages were renamed (`4_Models.py` →
`app/app_pages/3_Models.py`, `3_Model_Metrics.py` →
`app/app_pages/4_Model_Metrics.py`) and substantially built out (plain-
language factor labels, typeset equation rendering, a hover glossary, per-
fold signal-inclusion reporting) by the "View Equity/Bond Index Polynomial
Function" ticket, landed on this branch before this task started. Every
change below is against that current code.

- [x] Replaced the free `st.selectbox` on `3_Models.py` with `st.radio`
      ("Target"), options built dynamically from whichever roles
      `COMMITTED_TARGETS_KEY` actually resolved (`available_roles = [role
      for role in TargetRole if role in target_columns]`) — a role with
      nothing uploaded simply isn't offered, rather than shown disabled. No
      target resolved at all shows a guiding `st.info` and stops, instead of
      falling through to a free column picker.
- [x] `signal_cols` now excludes **every** resolved target column
      (`target_columns.values()`), not just the currently-selected one — this
      closes the leak the Phase 5 progress notes flagged on the live data
      (`SPX_Index_PX_BID` screened in as a signal for the SPX target itself
      in 118/124 folds).
- [x] Fama-French 5-Factor is dropped from the `family_options` list
      whenever `role == TargetRole.BOND`, rather than disabled — same
      "build the options list dynamically" approach as the target selector.
- [x] Every per-family session-state key (`POLYNOMIAL_RESULT_KEY`,
      `..._DESCRIPTION_KEY`, `FAMAFRENCH_*`, `ML_*`, and
      `POLYNOMIAL_FUNCTION_KEY`, which the original plan didn't anticipate
      since it postdates this plan) is now namespaced by role via a shared
      `_role_key(base, role) -> f"{base}_{role.value}"` helper, duplicated
      into `4_Model_Metrics.py` the same way the base key constants already
      were (a digit-prefixed filename still can't be imported from).
- [x] `reporting/model_metrics.py::build_metrics_rows()` gained an
      `inapplicable: Collection[str] = ()` parameter — a model named there
      renders `NOT_APPLICABLE` ("N/A — not applicable") instead of `NOT_RUN`
      when it has no result. `4_Model_Metrics.py` now loops over `TargetRole`
      rendering one section per role, each with its own `_results_for(role)`
      and `INAPPLICABLE[role]` (only `{"FF5 Benchmark"}` for Bond).
- [x] Tests: `tests/unit/test_model_metrics.py` — 2 new tests for
      `inapplicable`. `tests/functional/test_models_page.py` — 5 new tests
      (no-target guidance message, only-resolved-roles offered, FF5 absent
      for Bond, a target never appearing as a signal for the other role,
      switching target doesn't clobber the other's stored result); existing
      helpers updated to seed `extraction_committed_targets` and the
      role-namespaced keys. `tests/functional/test_glossary.py` — updated
      for the renamed "Target" control and the namespaced keys.
      `tests/functional/test_model_metrics_page.py` — new file, 6 tests for
      the two-section rendering (both sections always shown, empty-state per
      section, results don't leak across sections, FF5 reads "N/A — not
      applicable" under Bond vs. "Not run" under Equity).

Full suite green, `ruff check .` clean, verified in the browser (Models page
correctly shows the "no target resolved" guidance with nothing committed;
Model Metrics correctly shows both "Equity — S&P 500" and "Bond — US
Aggregate" sections).

### Task 4.3 — lock the forecast horizon to the two values the spec actually asks for

Found while checking the horizon/lag/embargo mechanics for correctness — not
originally in scope, flagging it here rather than changing it unasked:

- [x] The validation-metrics document requires exactly two horizons, h=1 and
      h=5 trading days, **reported separately, never averaged**, with a
      shared embargo equal to the *maximum* label horizon (5 days) — not a
      per-horizon embargo. Today's "Forecast horizon (days)" control on
      `4_Models.py` is a free `number_input` (any positive integer, default
      5), and embargo defaults to whatever horizon is currently typed in
      (`embargo = int(horizon)`) — so picking h=1 today also silently drops
      embargo to 1, which doesn't match the spec.
- [x] Replace the free horizon input with a choice of exactly "1 day" / "5
      days," **defaulting to 5 days**. Fix embargo at a constant 5 regardless
      of which horizon is selected, rather than deriving it from the selected
      horizon.
- [x] Signal lag stays a fixed 1 trading day by default, per spec — this is
      already correct (`lag_days` defaults to 1 and is independent of
      horizon); no change needed to the default. **Do** change how it's
      presented: there is no legitimate reason to run production with lag
      other than 1 (a larger lag only throws away usable recent data; a
      smaller one risks using data not yet published). The one real use for
      making it adjustable is the proposal's own Risk 2 mitigation — a
      deliberate "lag-shift audit" (re-run with one extra day of lag; a
      signal whose predictive power collapses was likely leaking). Move the
      lag control out of the main input row into an "Advanced: lag-shift
      audit" section (progressive disclosure, matching the proposal's own
      Risk 9 mitigation for non-technical users) rather than presenting it as
      a routine tunable next to horizon.

---

## Phase 5 — Remove the static Signal Screening tab; add per-fold inclusion visibility

**Files:** `app/app_pages/2_Signals.py` (delete), `app/Home.py` (remove from
navigation), `app/app_pages/4_Models.py` (add the replacement view)

- [x] Delete `app/app_pages/2_Signals.py` and its entry in `app/Home.py`'s
      `st.navigation`. Rationale: it runs one full-history rank-IC screen
      with no train/test split — a different, more optimistic computation
      than the per-fold screening the harness actually performs for ML and
      Derived-Polynomial — and showing both, unlabelled, misleads a reader
      into thinking they're the same number.
- [x] `src/forecasting_engine/features/screening.py` is **not** dead —
      `screen_over_folds()` is actively used by
      `validation/harness.py::evaluate(..., screen=True)`. Only the page
      goes, not the module.
- [x] Add, next to the existing fitted-terms/SHAP table on the Models page
      (meaningful only when `screen=True` is used, i.e. ML and Derived-
      Polynomial): a small table of each signal against how many of the
      walk-forward folds included it (e.g. "vix: 8/8", "fx_impl_vol: 0/8").
      **Decided:** add a field to `FoldResult` (e.g. `screened_signals:
      tuple[str, ...] | None`) recording exactly which signals `evaluate()`
      used to fit that fold — set it from the same `per_fold_screen` value
      `evaluate()` already computes internally (harness.py, `screen=True`
      path), not from a second, separate call to `screen_over_folds()`. A
      second call would risk silently disagreeing with what was actually fit
      if the two computations ever drift apart; reusing the exact value
      `evaluate()` already produced guarantees the displayed table matches
      reality.
- [x] Retire test coverage specific to the deleted page; add coverage for the
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
- Home tab redesign (past-run history, a downloadable report + inputs, saved
  on an explicit action after allocation is done) — raised by the team, not
  designed yet, not this sprint. Worth noting it lines up with "run
  persistence," which the proposal already names as a UAT Round 3 focus item
  — so this isn't scope creep, just not sequenced yet.

---

## Definition of done, per phase

- `uv run pytest` passes.
- `uv run ruff check .` passes.
- For any removal: a short before/after note (files removed, test count
  before → after) rather than a silent deletion.
- Manually exercise the affected Streamlit page(s) and confirm behaviour
  matches this spec before moving to the next phase — don't chain phases on
  an unverified previous one.

---

## Progress log — what was actually done (as of 18 Sep, after Task 4.2)

The build didn't follow the phase numbers. This records what landed, what was
done that the plan didn't ask for, and what's still open.

**Done and committed on `Toby`:**

- **Phase 1 (Tasks 1.1, 1.2), `5607f5e`.** CSV and XLSX both accepted on the
  open schema. Task 1.3 (resuming from a merged file) is still deferred.
- **Unplanned: the target-horizon bug, `9bbf9a0`.** Found during review, not
  in the original phases. The target's horizon is now counted in its own
  trading days, and `PurgedWalkForward` purges on `FeaturePanel.label_end`.
  Details are in review correction 1 at the top.
- **Plan review, `4a90170`.** The five review corrections, the new build order
  (3 → 5 → 4.3 → 4.1 → 2 → 4.2 → 6), and the `LBUSTRUU` bond-target decision,
  also recorded in `docs/bloomberg-exports.md`.
- **Phase 3, `ae5162b`.** Removed `quality/`, `ingest/schema.py`,
  `ingest/validation.py`, `store/validations.py`, `ingest/bloomberg.py`,
  `ingest/bloomberg_csv.py`, `ingest/workbook.py` and `convert.py`, plus the 14
  test files that only tested them. **Tests: 521 → 253**; the 268 removed are
  exactly the collected items in the deleted files. `extraction/targets.py`
  holds the salvaged ticker → target-role mapping. The MAD guards moved onto the
  live `extraction/validation.py`. Retired design docs are marked as records,
  not rewritten; the removed code is recoverable at `4a90170`.
- **Phase 5, `2d2eef2`.** The Signals page and its nav entry are gone. Models
  shows per-fold signal inclusion for derived-polynomial and ML runs. **Tests:
  253 → 267.** Deviates from the plan's `screened_signals` tuple: `evaluate()`
  falls back to every signal when screening keeps none, and the table must show
  a signal no fold used as 0/N, so `FoldResult.screening` records the candidates
  and what was kept, and derives what was fit. The fold is built from that same
  record, so the table can't drift from the fit. `run_screening` has no caller
  left; the plan keeps the screening module, so it is left for the team.
- **Phase 4.3, `036768a`.** Horizon is a required choice of 1 or 5 days
  (default 5); embargo is a constant 5 (`max(HORIZONS)`), no longer an input;
  lag lives in an "Advanced: lag-shift audit" section. **Tests: 267 → 274.** The
  embargo test captures what `PurgedWalkForward` is really built with and fails
  on the old `embargo = horizon`.
- **Unplanned: the "View Equity/Bond Index Polynomial Function" ticket,**
  `5cee4b8`–`d1f5606`. Landed on the `feature-raphael-...` branch, later
  fast-forward-merged into `Toby` (external to this plan's own commits).
  Covers what this plan's Phase 6 asked for and more: plain-language factor
  labels (`reporting/factor_labels.py`), typeset equation rendering
  (`reporting/polynomial_function.py`), a hover glossary (`app/glossary.py`),
  per-fold "how many folds kept any term" reporting, and
  `docs/validation-review.md` — an independent correctness audit (leakage
  controls, a measured null distribution for the promotion gate, a measured
  screening false-pass rate, a Fama-French unit-scale bug). Renamed
  `4_Models.py` → `app/app_pages/3_Models.py` and `3_Model_Metrics.py` →
  `app/app_pages/4_Model_Metrics.py` along the way — every later reference in
  this plan to the old filenames means the new ones.
- **Phase 4.1, `88721f7`.** Data page split into separate "Target index
  files" and "Signal files" uploaders; ticker detection pre-fills the role,
  always overridable; `COMMITTED_TARGETS_KEY` records whatever was resolved.
  **Tests: 274 → 301** (functional suite rewritten for the two-uploader
  shape plus 6 new target-specific tests).
- **Phase 2, `ffb6f0d`.** `forward_fill()`'s signature changed to `(frame,
  max_gap, *, exclude=())`; every signal gap fills automatically, targets
  never do. `_render_gap_review()` is now a summary of what's still missing,
  not an editable table — `gap_decisions_*`, the checkbox column, and
  "Clean all"/"Include all" are gone. **Tests: 301 → 304.**
- **Task 4.2.** `3_Models.py`'s target selector is now `st.radio` over
  exactly the resolved roles (no free column picker); `signal_cols` excludes
  every resolved target, not just the active one — this is what actually
  fixes the `SPX_Index_PX_BID`-as-a-signal leak noted below. FF5 dropped
  from the model-family options for the bond target. Every per-family
  session-state key namespaced by role via `_role_key()`.
  `reporting/model_metrics.py::build_metrics_rows()` gained `inapplicable=`;
  `4_Model_Metrics.py` renders one section per `TargetRole`. **Tests: 304 →
  317** (2 unit, 5 functional on `3_Models.py`, a new
  `test_model_metrics_page.py` with 6).

**Checks after Task 4.2:** `uv run pytest` shows 317 passed and `uv run ruff
check .` passes. Verified in the browser: the Data page's two upload
sections render; the Models page correctly shows "No target resolved yet"
with nothing committed; the Model Metrics page correctly shows both
"Equity — S&P 500" and "Bond — US Aggregate" sections.

**Checks after Phase 4.3:** `uv run pytest` shows 274 passed and `uv run ruff
check .` passes. Phase 5 was run end to end on four real exports (124 folds, the
inclusion table renders); Phase 4.3's controls were checked in the browser.

**Checks after Phase 3:** `uv run pytest` shows 253 passed and
`uv run ruff check .` passes. All five pages render in the browser with no
exceptions. End to end through the real Data and Models page scripts: the SPX
and Global Aggregate `.xlsx` exports upload and commit (2,600 rows), a derived
polynomial fits, and no training label reaches its test window across 123 folds
on the app's defaults. That run also covers Phase 1's manual check, which was
previously outstanding.

**Not started:** Phase 6 in its original form — superseded by the polynomial-
display ticket above, which covers the same ground; what's left (if anything)
is for the team to spot-check against the original Phase 6 checklist above.
Task 1.3 (resuming from a previously-merged file) stays deferred, per the
team's own instruction, pending a team discussion.

**Found along the way, for the team — status as of Task 4.2:**

- **An implausible model IC — still open, not caused by anything in this
  plan.** Deriving a polynomial for SPX 5-day returns reported an OOS rank
  IC of about 0.33 when first noticed; `docs/validation-review.md` (part of
  the polynomial-display ticket, independent of this plan) since re-measured
  the out-of-sample Rank IC at roughly +0.15 on the bond target and put it
  through seven leakage controls, all clean — real structure, not a pipeline
  artefact, though the two numbers weren't measured under identical
  settings. Its Open Item 1 is more urgent than it looked here: the
  promotion gate itself (`OOS_RANK_IC_GATE`, sponsor-confirmed at 0.02) lets
  a model with zero real skill pass roughly one time in three, from
  sampling noise alone — worth the team's attention ahead of anything shown
  to the sponsor.
- **The target's own sibling field screened in as a signal — fixed in Task
  4.2.** With SPX as the target, `SPX_Index_PX_BID` was fit on in 118 of 124
  folds before the structural target/signal split existed. `signal_cols`
  now excludes every resolved target column, not just the active one, which
  is what actually closes this (Phase 4.1 alone made the *uploads*
  structural; this is the exclusion that makes the *modelling* structural).
- **Screening barely filters — still open, quantified more precisely since
  this was first noted.** `docs/validation-review.md` measured it directly:
  a pure-noise signal clears `INCLUSION_THRESHOLD = 0.02` 84% of the time on
  a 120-day window. The threshold itself is still blocked in Section 0
  pending sponsor input; this number is evidence for that conversation, not
  a reason to change it unilaterally.
- **`fixtures.py` output is mislabelled by the live pipeline — still open.**
  It writes a flat fixed-contract CSV with no `Security` metadata, so every
  column comes back prefixed with the filename. Same root cause as deferred
  Task 1.3.
