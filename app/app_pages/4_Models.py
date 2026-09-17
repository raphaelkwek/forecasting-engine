"""Models page: FYP-42's Fama-French benchmark, FYP-43's polynomial forecasting
function, and FYP-44's machine-learning models — every model family built so far,
sharing one walk-forward harness.

Reads the dataset committed via "Use Updated Data" on the Data page. No maths
lives here — fitting is in forecasting_engine.models.polynomial / famafrench /
boosted; the walk-forward loop is in forecasting_engine.validation.harness.
"""

from __future__ import annotations

import streamlit as st

import bloomberg_extraction_panel
import ui
from forecasting_engine.extraction.bloomberg_csv import DATE_COLUMN
from forecasting_engine.ingest.align import align_and_lag
from forecasting_engine.models.base import ModelDescription
from forecasting_engine.models.boosted import BoostedConfigError, run_boosted
from forecasting_engine.models.famafrench import (
    FACTOR_COLUMNS,
    FamaFrenchDataError,
    merge_factors,
    run_famafrench,
)
from forecasting_engine.models.polynomial import (
    CANDIDATE_CONFIGS,
    MAX_DEGREE,
    DerivedPolynomial,
    PolynomialConfigError,
    run_derived_polynomial,
    run_user_polynomial,
)
from forecasting_engine.reporting.model_metrics import ModelRunResult
from forecasting_engine.validation.splitters import PurgedWalkForward

#: Where each model family's latest result is parked for the Model Metrics page.
#: Duplicated as a matching constant in app_pages/3_Model_Metrics.py — a page
#: filename starting with a digit isn't a valid Python module name, so it can't
#: be imported from there.
POLYNOMIAL_RESULT_KEY = "polynomial_result"
POLYNOMIAL_DESCRIPTION_KEY = "polynomial_description"
FAMAFRENCH_RESULT_KEY = "famafrench_result"
FAMAFRENCH_DESCRIPTION_KEY = "famafrench_description"
ML_RESULT_KEY = "ml_result"
ML_DESCRIPTION_KEY = "ml_description"

#: The forecast horizons the validation framework asks for, reported separately
#: and never averaged.
HORIZONS: tuple[int, ...] = (1, 5)

#: One embargo shared by every horizon, equal to the longest of them, rather than
#: one per horizon. Picking h=1 used to drop the embargo to 1 as well.
EMBARGO_DAYS: int = max(HORIZONS)

#: Signal lag in production. There is no legitimate reason to run with any other
#: value: a longer lag throws away usable data, a shorter one uses data not yet
#: published. Raising it is only for the lag-shift audit.
PRODUCTION_LAG_DAYS: int = 1

st.set_page_config(page_title="Models · Forecasting Engine", page_icon=":material/functions:")
ui.inject()

st.header("Models")
st.caption(
    "Fit a model family through the shared walk-forward harness — results report to "
    "the Model Metrics page."
)

merged = st.session_state.get(bloomberg_extraction_panel.COMMITTED_KEY)
if merged is None:
    st.info('No data committed yet — click "Use Updated Data" on the Data page first.')
    st.stop()

numeric_cols = [c for c in merged.columns if c != DATE_COLUMN and merged[c].dtype.kind in "fi"]
price_col = st.selectbox("Target price/level column", numeric_cols)
signal_cols = [c for c in numeric_cols if c != price_col]

if not price_col:
    st.info("Need at least a price column to model.")
    st.stop()

family = st.radio(
    "Model family",
    ["Polynomial", "Fama-French 5-Factor", "Machine Learning"],
    horizontal=True,
)

horizon = st.segmented_control(
    "Forecast horizon",
    HORIZONS,
    default=max(HORIZONS),
    required=True,
    format_func=lambda days: f"{days} day" if days == 1 else f"{days} days",
    help="How many trading days ahead to predict. Each horizon is run and reported "
    "separately — the two are never averaged.",
)

cols = st.columns(2)
train = cols[0].number_input(
    "Walk-forward train window (days)",
    min_value=10,
    value=120,
    step=10,
    help="How much history the model studies (120 days ≈ 6 months)",
)
test = cols[1].number_input(
    "Walk-forward test window (days)",
    min_value=1,
    value=20,
    step=5,
    help="The days right after training where we check if the predictions actually came true",
)
st.caption(
    f"Embargo is fixed at {EMBARGO_DAYS} trading days — the longest forecast horizon — "
    "whichever horizon is selected, so training and grading never overlap."
)

with st.expander("Advanced: lag-shift audit"):
    st.caption(
        f"Signals are lagged {PRODUCTION_LAG_DAYS} trading day, so each value is one that "
        "had already been published. Leave this alone for a normal run. To audit for "
        "look-ahead, run once, raise the lag by one day and run again: a signal whose "
        "predictive power collapses was probably leaking."
    )
    lag_days = st.number_input(
        "Signal lag (days)", min_value=1, value=PRODUCTION_LAG_DAYS, step=1
    )

splitter = PurgedWalkForward(train=int(train), test=int(test), embargo=EMBARGO_DAYS)

result: ModelRunResult | None = None
description: ModelDescription | None = None

if family == "Polynomial":
    result_key, description_key = POLYNOMIAL_RESULT_KEY, POLYNOMIAL_DESCRIPTION_KEY

    if not signal_cols:
        st.info("Need at least one other signal column, alongside the price column, to model.")
        st.stop()
    indexed = merged.set_index(DATE_COLUMN)
    panel = align_and_lag(
        indexed, signal_cols, price_col, horizon=int(horizon), lag_days=int(lag_days)
    )

    st.subheader("Polynomial forecasting function")
    st.caption(
        "Define the function directly, or let the system derive one (degree up to "
        f"{MAX_DEGREE}, regularized)."
    )
    mode = st.radio(
        "Function source", ["Enter a function", "Derive automatically"], horizontal=True
    )

    if mode == "Enter a function":
        st.caption(f"Available signal columns: {', '.join(panel.signals)}")
        formula = st.text_input(
            "Function (arithmetic on signal columns only — e.g. `2 * vix + credit_spread_hy ** 2`)"
        )
        if st.button("Apply", type="primary") and formula:
            try:
                result, description = run_user_polynomial(formula, panel, splitter)
            except PolynomialConfigError as exc:
                st.error(str(exc))
    else:
        degree_cols = st.columns(2)
        max_terms = degree_cols[0].number_input(
            "Max terms per candidate (optional cap)", min_value=1, value=10, step=1
        )
        st.caption(
            "Tries a small grid of degrees (1-3) and regularizers (Lasso, ElasticNet), "
            "compares them via PBO, and reports the one with the best out-of-sample rank IC."
        )
        if st.button("Derive", type="primary"):
            candidates = tuple(
                DerivedPolynomial(
                    degree=c.degree, regularizer=c.regularizer, max_terms=int(max_terms)
                )
                for c in CANDIDATE_CONFIGS
            )
            with st.spinner("Fitting candidate polynomials and estimating PBO…"):
                try:
                    result, description = run_derived_polynomial(
                        panel, splitter, candidates=candidates
                    )
                except PolynomialConfigError as exc:
                    st.error(str(exc))

elif family == "Fama-French 5-Factor":
    result_key, description_key = FAMAFRENCH_RESULT_KEY, FAMAFRENCH_DESCRIPTION_KEY

    st.subheader("Fama-French five-factor benchmark")
    factor_file = st.session_state.get(bloomberg_extraction_panel.FACTORS_KEY)
    if factor_file is None:
        st.info("No Fama-French factors loaded yet — download them on the Data page first.")
        st.stop()
    st.caption(
        "Regresses the target on the five Fama-French factors, lagged like any other "
        "signal, so every model's OOS Rank IC means the same thing. No configuration "
        "search happens, so no PBO is computed — same as a user-supplied polynomial."
    )
    try:
        with_factors = merge_factors(merged, factor_file.frame)
    except FamaFrenchDataError as exc:
        st.error(str(exc))
        st.stop()
    indexed = with_factors.set_index(DATE_COLUMN)
    panel = align_and_lag(
        indexed, list(FACTOR_COLUMNS), price_col, horizon=int(horizon), lag_days=int(lag_days)
    )

    if st.button("Fit", type="primary"):
        try:
            result, description = run_famafrench(panel, splitter)
        except FamaFrenchDataError as exc:
            st.error(str(exc))

else:
    result_key, description_key = ML_RESULT_KEY, ML_DESCRIPTION_KEY

    if not signal_cols:
        st.info("Need at least one other signal column, alongside the price column, to model.")
        st.stop()
    indexed = merged.set_index(DATE_COLUMN)
    panel = align_and_lag(
        indexed, signal_cols, price_col, horizon=int(horizon), lag_days=int(lag_days)
    )

    st.subheader("Machine learning (XGBoost / LightGBM)")
    st.caption(
        "Tunes XGBoost and LightGBM once each via Optuna, refits both per walk-forward "
        "fold with those fixed hyperparameters, compares them via PBO, and reports the "
        "one with the best out-of-sample rank IC. Feature attribution below is by SHAP."
    )
    n_trials = st.number_input(
        "Optuna trials per library",
        min_value=1,
        value=10,
        step=1,
        help="Kept small by default — tuning happens once per run, not once per fold.",
    )
    if st.button("Tune & Fit", type="primary"):
        with st.spinner("Tuning XGBoost and LightGBM, then fitting per fold…"):
            try:
                result, description = run_boosted(panel, splitter, n_trials=int(n_trials))
            except BoostedConfigError as exc:
                st.error(str(exc))

if result is not None and description is not None:
    st.session_state[result_key] = result
    st.session_state[description_key] = description
    st.success("Run complete — see Model Metrics for the full comparison.")

if result_key in st.session_state:
    if result is None:
        st.caption(
            "Showing the most recent run. Adjust the inputs above and run again to update it."
        )
    result = st.session_state[result_key]
    description = st.session_state[description_key]

    metric_cols = st.columns(4)
    metric_cols[0].metric("IC", f"{result.ic:.4f}" if result.ic == result.ic else "—")
    oos_rank_ic_text = (
        f"{result.oos_rank_ic:.4f}" if result.oos_rank_ic == result.oos_rank_ic else "—"
    )
    metric_cols[1].metric("OOS Rank IC", oos_rank_ic_text)
    metric_cols[2].metric("RMSE", f"{result.rmse:.4f}" if result.rmse == result.rmse else "—")
    metric_cols[3].metric("PBO", f"{result.pbo:.4f}" if result.pbo is not None else "N/A")

    st.markdown(ui.eyebrow("Crash diagnostics"), unsafe_allow_html=True)
    crash = result.crash
    st.caption(
        f"Recall {crash.recall:.4f} · Precision {crash.precision:.4f} · F1 {crash.f1:.4f} "
        f"({crash.n_true_tail_days} true tail day(s) in the walk-forward test windows)."
    )

    is_ml = family == "Machine Learning"
    value_col = "Mean |SHAP value|" if is_ml else "Coefficient"
    st.markdown(
        ui.eyebrow("Feature attribution (SHAP)" if is_ml else "Fitted terms"),
        unsafe_allow_html=True,
    )
    if description.terms:
        rows = [
            {"Term": term, value_col: coefficient}
            for term, coefficient in zip(description.terms, description.coefficients, strict=True)
        ]
        if description.intercept is not None:
            rows.append({"Term": "(intercept)", value_col: description.intercept})
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.caption("No terms survived fitting — every coefficient was regularized to zero.")

    # Only runs that screen per fold (derived polynomial, machine learning) have
    # this. getattr, not attribute access: a result kept in session state from
    # before this field existed shouldn't take the page down.
    screening = getattr(result, "screening", None)
    if screening is not None:
        st.markdown(ui.eyebrow("Signal inclusion across folds"), unsafe_allow_html=True)
        st.caption(
            f"How many of the {screening.folds} walk-forward folds were fit on each signal. "
            "Every fold screens signals on its own training window, so a signal can be "
            "kept in some folds and dropped in others."
        )
        st.dataframe(
            [
                {"Signal": signal, "Folds": f"{used}/{screening.folds}"}
                for signal, used in screening.counts
            ],
            width="stretch",
            hide_index=True,
        )
        if screening.fell_back:
            st.caption(
                f"{screening.fell_back} of {screening.folds} folds kept no signal after "
                "screening, so they were fit on every signal instead."
            )
