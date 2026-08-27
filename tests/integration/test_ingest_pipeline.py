"""CSV on disk to FeaturePanel, using the same path a user takes."""

import pandas as pd
import pytest

from forecasting_engine import fixtures
from forecasting_engine.config import DataSpec, RunConfig
from forecasting_engine.ingest.align import align_and_lag
from forecasting_engine.ingest.loader import load


@pytest.fixture
def signals_csv(tmp_path):
    path = tmp_path / "signals.csv"
    fixtures.main(["--years", "5", "--seed", "11", "--out", str(path)])
    return path


def test_full_ingest_produces_a_usable_panel(signals_csv):
    panel = align_and_lag(load(signals_csv))

    assert len(panel) > 1000
    assert panel.lag_days == 1
    assert panel.targets == ("spx_fwd_5d", "agg_fwd_5d")
    assert not panel.frame.isna().any().any()
    assert panel.frame.index.is_monotonic_increasing


def test_defects_are_reported_but_do_not_block(signals_csv):
    raw = load(signals_csv)
    assert raw.issues, "the fixture generator should have injected detectable defects"
    assert align_and_lag(raw) is not None


def test_matrix_is_ready_for_a_model(signals_csv):
    panel = align_and_lag(load(signals_csv))
    features, target = panel.matrix(panel.frame.index)

    assert list(features.columns) == list(panel.signals)
    assert len(features) == len(target)
    assert features.notna().all().all()


def test_the_pipeline_is_reproducible(signals_csv):
    first = align_and_lag(load(signals_csv))
    second = align_and_lag(load(signals_csv))
    pd.testing.assert_frame_equal(first.frame, second.frame)


def test_a_run_config_can_be_built_from_a_loaded_file(signals_csv):
    raw = load(signals_csv)
    config = RunConfig(data=DataSpec(path=raw.source.path, sha256=raw.source.sha256))
    assert config.run_id
    assert config.features.horizon_days == align_and_lag(raw).horizon_days
