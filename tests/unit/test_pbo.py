import pandas as pd
import pytest

from forecasting_engine.validation.pbo import compute_pbo


def _series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx)


def test_pbo_is_one_when_the_is_winner_never_repeats_out_of_sample():
    # "overfit": strong positive in the first half of history, strong
    # negative in the second half. "flat": mildly positive throughout.
    # Whichever one wins in-sample is the one whose edge doesn't survive
    # out-of-sample, in both of the two ways to split two blocks into IS/OOS.
    overfit = _series([0.10, 0.09, -0.09, -0.10])
    flat = _series([0.01, 0.00, 0.01, 0.02])

    result = compute_pbo({"overfit": overfit, "flat": flat}, n_blocks=2)

    assert result.pbo == 1.0
    assert result.n_combinations_tested == 2
    assert result.configurations_tested == ("overfit", "flat")


def test_pbo_is_zero_when_one_config_dominates_every_block():
    genuine = _series([0.030, 0.025, 0.028, 0.032])
    noise = _series([0.001, -0.001, -0.002, 0.001])

    result = compute_pbo({"genuine": genuine, "noise": noise}, n_blocks=2)

    assert result.pbo == 0.0


def test_requires_at_least_two_configurations():
    only_one = {"solo": _series([0.01, 0.02, 0.03, 0.04])}
    with pytest.raises(ValueError):
        compute_pbo(only_one, n_blocks=2)


def test_requires_even_n_blocks():
    configs = {
        "a": _series([0.01, 0.02, 0.03, 0.04, 0.05, 0.06]),
        "b": _series([0.02, 0.01, 0.04, 0.03, 0.06, 0.05]),
    }
    with pytest.raises(ValueError):
        compute_pbo(configs, n_blocks=3)


def test_n_combinations_tested_matches_choose_n_blocks_half():
    configs = {
        "a": _series([0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]),
        "b": _series([0.08, 0.07, 0.06, 0.05, 0.04, 0.03, 0.02, 0.01]),
    }
    result = compute_pbo(configs, n_blocks=4)
    assert result.n_combinations_tested == 6  # C(4, 2)
