import math

from forecasting_engine.reporting.model_metrics import (
    NO_CONFIG_SEARCH,
    NOT_RUN,
    Cell,
    ModelRunResult,
    build_metrics_rows,
)
from forecasting_engine.validation.crash import CrashDiagnostics


def _result(ic, oos_rank_ic, rmse, pbo, recall=0.6, precision=0.5, f1=0.5455, n_events=5):
    return ModelRunResult(
        ic=ic,
        oos_rank_ic=oos_rank_ic,
        rmse=rmse,
        pbo=pbo,
        crash=CrashDiagnostics(
            recall=recall, precision=precision, f1=f1, n_true_tail_days=n_events
        ),
    )


def test_missing_models_render_as_not_run_in_fixed_order():
    rows = build_metrics_rows({})

    names = [row["Model"].text for row in rows]
    assert names == ["FF5 Benchmark", "Polynomial", "Machine Learning"]
    for row in rows:
        assert row["IC"] == Cell(NOT_RUN)
        assert row["OOS Rank IC"] == Cell(NOT_RUN)
        assert row["PBO"] == Cell(NOT_RUN)


def test_row_order_is_fixed_regardless_of_input_order():
    results = {
        "Machine Learning": _result(0.03, 0.03, 0.02, 0.3),
        "FF5 Benchmark": _result(0.02, 0.025, 0.02, None),
        "Polynomial": _result(0.03, 0.03, 0.015, 0.4),
    }
    rows = build_metrics_rows(results)
    names = [row["Model"].text for row in rows]
    assert names == ["FF5 Benchmark", "Polynomial", "Machine Learning"]


def test_ff5_gets_no_gate_badge_and_na_pbo():
    results = {"FF5 Benchmark": _result(0.02, 0.025, 0.02, None)}
    row = build_metrics_rows(results)[0]

    assert row["OOS Rank IC"] == Cell("0.0250")
    assert row["PBO"] == Cell(NO_CONFIG_SEARCH)


def test_polynomial_gets_success_tone_when_both_gates_pass():
    results = {"Polynomial": _result(0.03, 0.03, 0.015, 0.4)}
    row = build_metrics_rows(results)[1]

    assert row["OOS Rank IC"] == Cell("0.0300", "success")
    assert row["PBO"] == Cell("0.4000", "success")
    assert row["Crash Recall"] == Cell("0.6000")
    assert row["Crash Precision"] == Cell("0.5000")
    assert row["Crash F1"] == Cell("0.5455")


def test_ml_gets_danger_tone_when_both_gates_miss():
    results = {"Machine Learning": _result(0.03, 0.01, 0.02, 0.6)}
    row = build_metrics_rows(results)[2]

    assert row["OOS Rank IC"] == Cell("0.0100", "danger")
    assert row["PBO"] == Cell("0.6000", "danger")


def test_values_rounded_to_requested_decimals():
    results = {"Polynomial": _result(0.03456, 0.03, 0.015, 0.4)}
    row = build_metrics_rows(results, decimals=2)[1]

    assert row["IC"] == Cell("0.03")


def test_nan_metric_renders_as_an_em_dash():
    results = {"Polynomial": _result(0.03, 0.03, 0.015, 0.4, recall=math.nan)}
    row = build_metrics_rows(results)[1]

    assert row["Crash Recall"] == Cell("—")
