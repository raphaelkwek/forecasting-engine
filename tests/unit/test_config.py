import pytest

from forecasting_engine.config import DataSpec, FeatureSpec, ModelSpec, RunConfig, SplitSpec

DATA = DataSpec(path="data/raw/signals.csv", sha256="d" * 64)


def test_defaults_match_the_spec_assumptions():
    config = RunConfig(data=DATA)
    assert config.features.horizon_days == 5
    assert config.features.lag_days == 1
    assert config.split.embargo_days == 6  # horizon + 1
    assert config.seed == 42


def test_identical_configs_share_a_run_id():
    assert RunConfig(data=DATA).run_id == RunConfig(data=DATA).run_id


def test_changing_the_seed_changes_the_run_id():
    assert RunConfig(data=DATA).run_id != RunConfig(data=DATA, seed=43).run_id


def test_changing_the_data_hash_changes_the_run_id():
    other = DataSpec(path="data/raw/signals.csv", sha256="e" * 64)
    assert RunConfig(data=DATA).run_id != RunConfig(data=other).run_id


def test_changing_the_model_degree_changes_the_run_id():
    a = RunConfig(data=DATA, model=ModelSpec(degree=3))
    b = RunConfig(data=DATA, model=ModelSpec(degree=5))
    assert a.run_id != b.run_id


def test_run_id_is_a_short_hex_string():
    run_id = RunConfig(data=DATA).run_id
    assert len(run_id) == 16
    assert all(character in "0123456789abcdef" for character in run_id)


def test_config_is_immutable():
    config = RunConfig(data=DATA)
    with pytest.raises(Exception):
        config.seed = 1


def test_embargo_shorter_than_the_horizon_is_rejected():
    with pytest.raises(ValueError, match="embargo"):
        RunConfig(
            data=DATA,
            features=FeatureSpec(horizon_days=5),
            split=SplitSpec(embargo_days=2),
        )


def test_portfolio_defaults_to_a_benchmark_comparison():
    assert RunConfig(data=DATA).portfolio.benchmark == "equal_weight"


def test_model_params_are_hashable():
    config = RunConfig(data=DATA, model=ModelSpec(params=(("alpha", 0.1),)))
    assert config.run_id
