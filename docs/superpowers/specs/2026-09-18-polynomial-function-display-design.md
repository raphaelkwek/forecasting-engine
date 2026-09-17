# Polynomial Function Display — Design

**Date:** 2026-09-18
**Status:** Approved
**Ticket:** View Equity/Bond Index Polynomial Function (subtasks build on FYP-122's stored artifact)
**Related:** Phase 6 of `../plans/2026-09-17-ingestion-consolidation-and-sprint2-fixes.md`;
`models/polynomial.py` (FYP-43); `validation/harness.py::summarize` (FYP-122)

## 1. Problem

The user story: *as a portfolio manager, I want to see the exact terms and coefficients of
the fitted equity/bond return forecast polynomial, so that I understand the feature
attribution.*

The Models page already shows the fitted polynomial, as a "Fitted terms" table. It falls
short of every acceptance criterion:

- **Raw internal names.** Terms are scikit-learn feature names built from open-schema
  column names: `VIX_Index_PX_LAST^2 LUACOAS_Index_PX_LAST`, where a space means
  multiplication.
- **No exponent breakdown.** The power is buried in the term string.
- **Unrounded coefficients.** Floats straight from the fit.
- **No origin label.** Nothing says whether the function was typed in or derived.
- **A user-supplied function isn't broken into terms at all.** `UserPolynomial.describe()`
  reports the whole formula as one "term" with coefficient 1.0.
- **No target.** `align_and_lag` renames the target to `fwd_return_{h}d`, so once a run
  finishes nothing records which index or horizon the function forecasts.

Re-rendering after a new run already works: a run writes its result to session state and
the page reads it back in the same rerun. What's missing is a warning when the shown
function no longer matches the page's inputs or data.

## 2. Acceptance criteria and how each is met

| Criterion | Met by |
|---|---|
| Equation rendered in readable maths notation (term, exponent, coefficient) | A typeset equation (`st.latex`) plus a table with one row per term: factor, exponent, coefficient (§4.2, §4.3) |
| Each factor shown with a plain-language label (e.g. "VIX"), not a raw code | `reporting/factor_labels.py` (§4.1) |
| Coefficients rounded to an agreed number of significant digits | `SIGNIFICANT_DIGITS = 4`, a working default until the team agrees a number (§4.3) |
| Labelled "User-Supplied Function" or "Derived Function" | An explicit `origin` passed by the page (§4.2) |
| Display refreshes automatically when a new function is derived or uploaded | Saved and rendered in the same rerun as the run, with a stale-function warning (§5) |

## 3. Scope

**In scope**
- Plain-language labels for signal and target columns.
- Parsing a derived fit's terms, and expanding a user-supplied formula into terms.
- Rounding, the LaTeX equation and the term table.
- The heading (origin), the target line and the stale-function warning on the Models page.

**Out of scope**
- Keeping separate equity and bond functions side by side. That's Phase 4.2's storage
  change, together with its target picker and the Model Metrics split. This ticket shows
  which target a function was fitted for, and nothing more.
- Labels on the Fama-French or machine-learning tables.
- Showing the function on the Model Metrics page.
- Clearing stored model results from the Data page when data is cleared or recommitted (§5).

## 4. Components

Three pure-Python modules with no Streamlit imports, each unit-testable on its own. The
page only wires them together.

### 4.1 `reporting/factor_labels.py`

Turns an open-schema column name into a plain-language label.

Column names are `{security}_{field}`, built by `extraction.bloomberg_csv.label()`, e.g.
`VIX_Index_PX_LAST`. Bloomberg exports carry only the ticker in their metadata
(`Security,VIX Index`), with no long name, so labels come from a lookup table in code.

```python
SECURITY_LABELS: Mapping[str, str]   # "VIX Index" -> "VIX"
FIELD_LABELS: Mapping[str, str]      # "PX_LAST" -> "last price"

def labeller(columns: Iterable[str]) -> Callable[[str], str]: ...
```

`labeller(columns)` returns a function mapping each column to its label. It takes the
full set of committed columns so it can decide when a field needs naming:

- **Splitting a name.** Find the Bloomberg yellow key (`Index`, `Comdty`, `Curncy`,
  `Govt`, `Corp`, `Equity`). Everything before it plus the key is the security
  (`VIX_Index` → `VIX Index`). Everything after is the field (`PX_LAST`).
- **Known security.** Use its label: `VIX_Index_PX_LAST` → "VIX". Add the field label
  in brackets only when another committed column shares the same security, e.g.
  `SPX_Index_PX_BID` → "S&P 500 (bid)" next to `SPX_Index_PX_LAST` → "S&P 500 (last price)".
- **Unknown security.** Use a tidied form, not the raw code: `ABC_Index_PX_LAST` →
  "ABC Index (last price)". An unknown field is shown with underscores as spaces.
- **No yellow key found.** Underscores become spaces, e.g. `spx_close` → "spx close".
  This is only a fallback, so the page never shows a bare internal code.

Initial table. The wording is a working default and the module docstring says so, so the
team can change it in one place:

| Security | Label |
|---|---|
| `SPX Index` | S&P 500 |
| `LBUSTRUU Index` | US Aggregate Bond |
| `LEGATRUU Index` | Global Aggregate Bond |
| `VIX Index` | VIX |
| `LUACOAS Index` | US IG credit spread |
| `LF98OAS Index` | US HY credit spread |
| `USGGBE10 Index` | US 10y breakeven |
| `JPMVXYG7 Index` | G7 FX implied vol |

| Field | Label |
|---|---|
| `PX_LAST` | last price |
| `PX_BID` | bid |
| `TOT_RETURN_INDEX_GROSS_DVDS` | total return |

### 4.2 `reporting/polynomial_function.py`: the model

```python
class Origin(StrEnum):
    USER_SUPPLIED = "User-Supplied Function"
    DERIVED = "Derived Function"

@dataclass(frozen=True)
class Term:
    coefficient: float
    factors: tuple[tuple[str, int], ...]   # ((column, power), ...), sorted by column

@dataclass(frozen=True)
class PolynomialFunction:
    origin: Origin
    target: str                  # the price column the target return was built from
    horizon: int                 # trading days
    intercept: float
    terms: tuple[Term, ...]      # empty when no term survived, or in formula-only mode
    formula: str | None          # set only when a user formula couldn't be expanded

def from_description(
    description: ModelDescription, *, origin: Origin, target: str, horizon: int
) -> PolynomialFunction: ...
```

**`origin` is passed in, not inferred.** The page knows whether "Apply" or "Derive" ran.
`ModelDescription.name` isn't a reliable signal: the model reports `"DerivedPolynomial"`,
while the existing page test builds one named `"Derived polynomial"`.

**Derived.** Each term name comes from `PolynomialFeatures.get_feature_names_out`: factors
separated by a single space, each either `column` or `column^k`. The intercept is
`description.intercept`, or 0.0 when it's `None`. A term that doesn't parse becomes a
`Term` with one factor, `(raw_name, 1)`. It still shows with its coefficient and a
best-effort label, and never raises.

Open-schema column names can't contain a space or `^`, because
`bloomberg_csv.label()` replaces every non-word character with `_`. That's what makes
the split safe.

**User-supplied.** The formula is `description.terms[0]`. It's parsed with the existing
`polynomial._parse`, which is already structurally validated, since the run succeeded.
The syntax tree is then expanded into a sum of monomials:

- **Constants and names** become one monomial each.
- **`+`, `-`, unary `+` and unary `-`** combine, pass through or negate monomial lists.
- **`*`** multiplies every pair of monomials, adding the powers of shared factors.
- **`**k`** (a whole number, already validated) multiplies the expression by itself k
  times. `x**0` is 1.
- **`/` by a constant expression** (no names in it) scales every coefficient by
  1/constant.
- **`/` by an expression containing a name** isn't a polynomial, so expansion stops.
- **Like terms** (the same factors and powers) are merged. Terms with coefficient 0 are
  dropped. The constant monomial becomes `intercept`.
- **Cap.** If the working expansion exceeds `MAX_EXPANDED_TERMS = 50` terms, expansion
  stops.

When expansion stops, the function is returned with `terms=()`, `intercept=0.0` and
`formula` set to the original formula. This is formula-only mode (§4.3).

The expansion helpers live in this module and import `_parse` from `models.polynomial`.
`_parse` stays where it is. Importing a private helper across modules is an accepted
cost here, because both modules own the same formula grammar. The alternative, making it
public, isn't needed yet.

### 4.3 Rendering helpers (same module)

```python
SIGNIFICANT_DIGITS: int = 4

def significant(value: float, digits: int = SIGNIFICANT_DIGITS) -> str: ...
def to_latex(fn: PolynomialFunction, label: Callable[[str], str]) -> str: ...
def term_rows(fn: PolynomialFunction, label: Callable[[str], str]) -> list[dict[str, str]]: ...
```

`SIGNIFICANT_DIGITS` is documented as a working default, not yet team-agreed, the same
way `INCLUSION_THRESHOLD` is.

**`significant`:**
- Rounds to `digits` significant figures and keeps trailing zeros:
  `significant(0.000231)` is `"0.0002310"`.
- Zero is `"0"`.
- Negative values use a true minus sign, `−`.
- When the absolute value is below `1e-4` or at least `1e6`, it switches to scientific
  form: `"1.234 × 10^-5"`. `to_latex` renders that as `1.234 \times 10^{-5}`.
- The same rounding applies to the intercept.

**`to_latex`:**
- Produces `\hat{y} = c_0 + c_1\,\text{VIX}^{2} - c_2\,\text{VIX}\,\text{US IG credit spread}`.
- The intercept comes first. It's omitted when it's 0 and at least one term exists.
- Each term's sign is written between terms rather than as `+ -`.
- A coefficient of exactly ±1 after rounding is dropped from the term, giving
  `\text{VIX}` not `1\,\text{VIX}`, but the sign is kept.
- Power 1 has no exponent.
- Labels are wrapped in `\text{}` with `\ & % $ # _ { } ~ ^` escaped.
- With no terms and no formula, it's `\hat{y} = c_0`.
- **Formula-only mode:** the formula is written back out from its syntax tree, with
  brackets only where operator precedence needs them. Each name becomes its labelled
  `\text{}`, `**k` becomes a superscript and division is written as `/`.

**`term_rows`:** one row per term, in the same order as the equation, all string values
so `st.dataframe` can't reformat them:

| Factor | Exponent | Coefficient |
|---|---|---|
| (intercept) | — | 0.001234 |
| VIX | 2 | 0.0004521 |
| VIX × US IG credit spread | 1 × 1 | −0.0002310 |

In formula-only mode `term_rows` returns `[]`.

## 5. Page changes (`app/app_pages/3_Models.py`)

New session key `POLYNOMIAL_FUNCTION_KEY = "polynomial_function"`, stored as a tuple of
`(PolynomialFunction, fingerprint)`.

**Dataset fingerprint:** `(len(merged), first date, last date, tuple(merged.columns))`
of the committed frame.

**When a run succeeds.** In the Polynomial branch, "Apply" sets `origin =
Origin.USER_SUPPLIED` and "Derive" sets `origin = Origin.DERIVED`. When the run returns
without error, in the same rerun:

```python
fn = from_description(description, origin=origin, target=price_col, horizon=int(horizon))
st.session_state[POLYNOMIAL_FUNCTION_KEY] = (fn, fingerprint(merged))
```

It's saved alongside the existing result and description keys, so a new run of either
origin always replaces the previous function.

**When a run fails.** Nothing is saved, so the previous function stays shown under the
existing "Showing the most recent run" caption.

**Display.** When `family == "Polynomial"` and the key exists, the "Fitted terms" block
is replaced by:

1. A subheading: `fn.origin` ("User-Supplied Function" / "Derived Function").
2. A caption: "Forecasts: {label(target)}, {horizon}-day return", or "1-day return".
3. **A stale warning (`st.warning`), if any apply**, checked in this order and showing
   only the first match:
   - The stored fingerprint differs from the current committed frame: "Fitted on a
     previous dataset. Run again to update."
   - `fn.target != price_col` or `fn.horizon != horizon`: "Fitted for {label(fn.target)},
     {fn.horizon}-day return. The inputs above have changed, so run again to update."
4. `st.latex(to_latex(fn, label))`.
5. The term table from `term_rows`. In formula-only mode, a caption instead: "This
   function can't be written as separate terms and exponents (it divides by a signal, or
   expands to more than 50 terms), so it's shown as entered."
6. The existing "No terms survived fitting" caption, unchanged, when a derived fit has no
   terms.

`label` is `labeller(numeric_cols)` built from the committed frame.

Fama-French and machine learning keep their existing table. The signal-inclusion table
stays where it is.

**Why a warning instead of clearing on data change.** Clearing from the Data page would
mean `bloomberg_extraction_panel.py` importing the Models page's session keys, which are
already duplicated in `4_Model_Metrics.py`. It would also clear Fama-French and ML results,
which is outside this ticket. The warning keeps the change inside the Models page.

## 6. Error handling

| Case | Behaviour |
|---|---|
| A derived fit with every coefficient regularized to zero | ŷ = intercept, an intercept-only table and the existing caption |
| A derived term name that doesn't parse | Kept as one raw factor with its coefficient, never raises |
| A user formula dividing by a signal, or expanding past 50 terms | Formula-only mode (§4.3) |
| Like terms that cancel (`vix - vix`), or a constant-only formula | Merged, zeros dropped, ŷ = constant |
| Division by a constant (`vix / 2`) | Coefficient 0.5 |
| A coefficient of ±1 | Equation omits the 1, the table shows it |
| LaTeX special characters in a label | Escaped |
| A session stored before this change (no function key) | The polynomial display is skipped and the page's existing metrics still render. The next run fills the key. |

## 7. Testing

**`tests/unit/test_factor_labels.py`:**
- Known securities map to their labels.
- A field is added only when two committed columns share a security.
- An unknown security gets the tidied fallback, and so does a name with no yellow key.

**`tests/unit/test_polynomial_function.py`:**
- **Derived parsing:** a power term, an interaction term, a power times an interaction,
  intercept handling (`None` → 0.0), no surviving terms, and an unparseable term name.
- **User expansion:**
  - A plain sum, and `(a + b)**2` → a², 2ab, b².
  - A constant moving into the intercept, and unary minus.
  - Division by a constant, and like terms cancelling.
  - `x**0`.
  - Division by a signal → formula-only.
  - An expansion past 50 terms → formula-only.
- **An equivalence check:** for several formulas, evaluating the expanded terms on random
  data equals `UserPolynomial(formula).predict(...)` on the same panel, to floating-point
  tolerance. This tests the maths, not just the formatting.
- **`significant`:** 4 digits with trailing zeros kept, negatives, zero, and both
  scientific-notation boundaries.
- **`to_latex`:** sign handling, a coefficient of ±1, power 1, escaping, intercept-only,
  and formula-only.
- **`term_rows`:** order, string values, and the "1 × 1" exponent for interactions.

**`tests/functional/test_models_page.py`** (AppTest). Following the existing tests, stored
runs are put straight into session state and not fitted:
- A stored derived function shows "Derived Function", the target line, labels like "VIX"
  and no raw `VIX_Index_PX_LAST` in the term table.
- Entering a formula and clicking "Apply" (fast and deterministic) replaces a stored
  derived function with "User-Supplied Function".
- A stored function with a different horizon or target from the page's inputs shows the
  stale warning, and so does one with a different dataset fingerprint.
- A session with a result but no function key renders without error.

**Definition of done:**
- `uv run pytest` and `uv run ruff check .` pass.
- A manual browser check on the Models page with real exports: a derived function and a
  user-supplied one both render with labels, rounding and the correct heading.

## 8. Open items for the team

- **The significant-digit count.** 4 is a working default.
- **The label wording** in §4.1's table.
- **The IC check.** Phase 3's progress log notes an implausible OOS rank IC (about 0.33)
  from fitting raw price levels. Worth resolving before this display is shown to the
  sponsor, since it presents that fit's coefficients as the model's attribution.
