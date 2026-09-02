# The data quality report: shared contract and decisions

`src/forecasting_engine/quality/report.py` is written into by four tickets:

| Ticket | Writes |
|---|---|
| FYP-8 | Schema validation — missing columns, type errors, range breaches |
| FYP-9 | Outlier detection — statistical flags the user includes or excludes |
| FYP-10 | Data gaps, once market holidays and weekends are ruled out |
| FYP-25 | Nothing. It *reads* everything and renders the report |

Their acceptance criteria pull in different directions in five places. This
document records how each was resolved and why, so that whoever picks up FYP-9,
FYP-10 or FYP-25 does not rediscover the argument or quietly resolve it the
other way. **Changing any of these breaks a sibling ticket.**

Status: settled as of FYP-8. Raise a change with the team rather than editing
the model to suit one ticket.

---

## 1. Severity is three-way, not blocking/clean

**The conflict.** FYP-8 needed two classes: faults that make a file
uninterpretable and stop the pipeline, and contract deviations worth reporting
that do not. FYP-9 and FYP-25 both require the opposite of blocking — FYP-9 says
flagged values are "retained in the dataset and not automatically removed or
altered", and FYP-25 says "flagged anomalies are informational only; the user
can proceed to forecasting regardless of flags". A two-value severity forces
outliers into the same bucket as schema warnings, and the distinction between
"your file breaches the documented range" and "this value is statistically
unusual, your call" disappears.

**Resolved.** Three levels:

| Severity | Meaning | Who raises it |
|---|---|---|
| `BLOCKING` | The file cannot be interpreted. Pipeline halts. | FYP-8 only |
| `WARNING` | A documented contract deviation. Pipeline proceeds. | FYP-8 |
| `INFO` | Observed and recorded. Entirely the user's call. | FYP-9, FYP-10 |

**Consequence for FYP-9 and FYP-10.** Never emit `BLOCKING`. An outlier or a
gap must not stop a run, however extreme. `QualityReport.passed` is defined as
"no blocking findings", so emitting one from an outlier check would silently
break FYP-25's fourth acceptance criterion.

## 2. Findings carry a stable id, derived from facts and never from prose

**The conflict.** FYP-9 requires the portfolio manager to "review each flagged
outlier and choose to include or exclude it before the forecasting engine runs".
That decision has to attach to something. FYP-9 also says detection "runs
automatically on every data upload", so the same outlier will be re-derived on
every run and must match the decision already made about it. Nothing in FYP-8
needed identity at all — its findings were rendered once and discarded.

**Resolved.** `QualityFinding.id` is a hash of `check`, `signal`, `dates`,
`rows` and `value` — what the finding is *about*. It deliberately excludes
`detail`, the human-readable message, so that rewording a message does not
orphan a decision. There is a test for this.

`decided()` returns a copy rather than mutating; findings are frozen.

**Consequence for FYP-9.** Do not put varying text in `detail` and expect ids to
hold — they will, which is the point, but equally do not encode anything
identifying *only* in `detail`. If two outliers must be distinguishable, they
must differ in signal, date, row or value.

## 3. A check that has not run is pending, not absent

**The conflict.** FYP-25's fifth criterion: "given Module 1 validation hasn't
completed, the report shows a 'Pending' state rather than a blank or broken
view". An absent section and a section with nothing to report are
indistinguishable if the model only holds findings.

**Resolved.** `KNOWN_CHECKS` lists every check in display order.
`QualityReport.pending()` produces a report where all of them are
`CheckStatus.PENDING`. `with_section()` replaces the placeholder in place rather
than appending, so ordering is stable as checks fill in. A check not in the
registry is appended, so a new one needs no registry edit to work.

`CheckStatus` is four-valued: `PENDING`, `PASSED`, `FLAGGED`, `FAILED`.

**Consequence for FYP-9 and FYP-10.** Register your check in `KNOWN_CHECKS` and
always emit a section — `PASSED` when you ran and found nothing, never silence.
Silence is indistinguishable from not having run.

## 4. A finding is located by signal *and* date, not by row number

**The conflict.** FYP-8 located problems by CSV line number, which is what a
user fixing a malformed file needs. FYP-9 requires each flagged outlier to
appear "with the affected signal, date, and value" — a line number is useless
for judging whether a spike is a real market event. FYP-25 needs a "per-signal
breakdown expandable from a summary", which requires the signal to be a field
you can group on, not prose inside a message.

**Resolved.** `QualityFinding` carries `signal`, `dates`, `rows`, `value` and
`count` as separate fields. `signal` is `None` for whole-file problems, which
`by_signal()` excludes and `whole_file` collects.

FYP-8's adapter looks up the date of each offending row from the file, so schema
findings carry dates too. It skips this when the date column is itself the
broken one — quoting back a date we could not parse would be circular.

**Consequence for FYP-25.** `by_signal()` groups across *every* check, so one
signal's expander shows its schema faults, its gaps and its outliers together.
That is the intended reading of "per-signal breakdown".

## 5. Coverage is data-level, separate from findings

**The conflict.** FYP-25's first criterion wants "ingested data date range and
count of missing values filled, per signal". Neither is a finding — a date range
is not a problem, and a filled gap is a repair rather than a fault. Modelling
them as findings would inflate every count in the summary.

**Resolved.** `Coverage` holds rows, columns and the date range, and hangs off
the report rather than off any check. Per-check numbers — thresholds, counts,
the market calendar used — go in `QualitySection.stats`, a free-form mapping.

**Consequence for FYP-10.** Its third criterion, "the market calendar source
used is documented for auditability", is satisfied by putting the calendar name
and version in `stats`, where it is serialised with the report. Do not bury it
in a `detail` string.

**Consequence for the missing-values work.** "Count of missing values filled,
per signal" belongs in the `missing` section's `stats`, not as one finding per
filled cell.

---

## Left open, deliberately

**Where per-finding decisions are persisted.** FYP-9 needs somewhere to store
include/exclude choices. The model supports it — findings have stable ids and
`decided()` — but no table exists. That schema is better designed with FYP-9's
requirements in hand than guessed at now. The report itself is currently
assembled on demand from the upload and the validation log rather than stored;
`as_dict()`/`from_dict()` exist for whoever needs to change that.

**Thresholds.** FYP-9 names "a set number of standard deviations or IQR" without
choosing. That is FYP-9's decision; record whichever it picks in the section's
`stats` so a report is self-describing.
