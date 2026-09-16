import numpy as np
import pandas as pd
import pytest

from forecasting_engine.ingest.align import FeaturePanel
from forecasting_engine.models.polynomial import (
    MAX_DEGREE,
    DerivedPolynomial,
    PolynomialConfigError,
    UserPolynomial,
)


def _formula_panel(n: int = 10) -> FeaturePanel:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    frame = pd.DataFrame(
        {"vix": range(n), "credit_spread_hy": range(n), "target": range(n)}, index=idx
    )
    return FeaturePanel(
        frame=frame, signals=("vix", "credit_spread_hy"), targets=("target",), lag_days=1
    )


# --- UserPolynomial: FYP-118, FYP-125 ---------------------------------------


def test_user_polynomial_applies_directly_with_no_fitting():
    panel = _formula_panel()
    model = UserPolynomial("2 * vix + credit_spread_hy ** 2")

    model.fit(panel, panel.frame.index)  # must be a no-op, not raise
    predicted = model.predict(panel, panel.frame.index)

    expected = 2 * panel.frame["vix"] + panel.frame["credit_spread_hy"] ** 2
    assert list(predicted) == list(expected.astype(float))


def test_user_polynomial_describe_reports_the_formula_as_its_own_term():
    description = UserPolynomial("vix + 1").describe()
    assert description.terms == ("vix + 1",)
    assert description.coefficients == (1.0,)


def test_user_polynomial_rejects_invalid_syntax():
    with pytest.raises(PolynomialConfigError):
        UserPolynomial("vix +")


def test_user_polynomial_rejects_function_calls_at_construction():
    # Structural rejection must happen eagerly, not deferred to predict() —
    # a portfolio manager's text box is untrusted input.
    with pytest.raises(PolynomialConfigError):
        UserPolynomial("abs(vix)")


def test_user_polynomial_rejects_non_integer_exponent_at_construction():
    with pytest.raises(PolynomialConfigError):
        UserPolynomial("vix ** 0.5")


def test_user_polynomial_rejects_unknown_column_at_predict():
    panel = _formula_panel()
    model = UserPolynomial("unknown_signal * 2")
    with pytest.raises(PolynomialConfigError):
        model.predict(panel, panel.frame.index)


# --- DerivedPolynomial: FYP-119, FYP-120, FYP-124 ---------------------------


def _linear_panel(n: int = 60) -> FeaturePanel:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    rng = np.random.default_rng(0)
    x = rng.normal(size=n)
    frame = pd.DataFrame({"x": x, "target": 2 * x}, index=idx)
    return FeaturePanel(frame=frame, signals=("x",), targets=("target",), lag_days=1)


def test_derived_polynomial_rejects_degree_above_five():
    with pytest.raises(PolynomialConfigError):
        DerivedPolynomial(degree=MAX_DEGREE + 1)


def test_derived_polynomial_rejects_unknown_regularizer():
    with pytest.raises(PolynomialConfigError):
        DerivedPolynomial(regularizer="ridge")


def test_derived_polynomial_recovers_a_clean_linear_relationship():
    # Regularization shrinks the coefficient, so this asserts structural
    # correctness (right term, right sign, fits well) rather than an exact
    # coefficient match — see the plan's note on why exact matching doesn't
    # hold under L1/L2 regularization.
    panel = _linear_panel()
    model = DerivedPolynomial(degree=1, regularizer="lasso")

    model.fit(panel, panel.frame.index)
    predicted = model.predict(panel, panel.frame.index)

    actual = panel.frame["target"]
    residual = ((predicted - actual) ** 2).sum()
    total = ((actual - actual.mean()) ** 2).sum()
    r_squared = 1 - residual / total
    assert r_squared > 0.9

    description = model.describe()
    assert "x" in description.terms
    coefficient = description.coefficients[description.terms.index("x")]
    assert coefficient > 0


def test_derived_polynomial_max_terms_caps_the_surviving_term_count():
    idx = pd.date_range("2024-01-01", periods=60, freq="D")
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({f"x{i}": rng.normal(size=60) for i in range(4)}, index=idx)
    frame["target"] = frame["x0"] * 2 - frame["x1"]
    panel = FeaturePanel(
        frame=frame, signals=tuple(f"x{i}" for i in range(4)), targets=("target",), lag_days=1
    )
    model = DerivedPolynomial(degree=2, regularizer="lasso", max_terms=3)

    model.fit(panel, panel.frame.index)

    assert len(model.describe().terms) <= 3


def test_derived_polynomial_rejects_too_few_training_rows():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    frame = pd.DataFrame({"x": range(5), "target": range(5)}, index=idx)
    panel = FeaturePanel(frame=frame, signals=("x",), targets=("target",), lag_days=1)

    with pytest.raises(PolynomialConfigError):
        DerivedPolynomial().fit(panel, panel.frame.index)


def test_derived_polynomial_predict_before_fit_raises():
    panel = _linear_panel()
    with pytest.raises(RuntimeError):
        DerivedPolynomial().predict(panel, panel.frame.index)
