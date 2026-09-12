import numpy as np
import pandas as pd

from forecasting_engine.validation.metrics import rank_ic


def test_rank_ic_perfect_positive_correlation():
    signal = pd.Series([1, 2, 3, 4, 5])
    target = pd.Series([10, 20, 30, 40, 50])
    assert rank_ic(signal, target) == 1.0


def test_rank_ic_perfect_negative_correlation():
    signal = pd.Series([1, 2, 3, 4, 5])
    target = pd.Series([50, 40, 30, 20, 10])
    assert rank_ic(signal, target) == -1.0


def test_rank_ic_drops_nan_pairs():
    signal = pd.Series([1, 2, np.nan, 4, 5])
    target = pd.Series([10, 20, 30, np.nan, 50])
    assert rank_ic(signal, target) == 1.0


def test_rank_ic_nan_when_fewer_than_two_pairs():
    signal = pd.Series([1, np.nan])
    target = pd.Series([np.nan, 20])
    assert np.isnan(rank_ic(signal, target))
