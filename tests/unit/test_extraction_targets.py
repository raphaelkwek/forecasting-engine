"""The target ticker mapping."""

from forecasting_engine.extraction.targets import PREFERRED_FIELD, TARGET_TICKERS, TargetRole


def test_each_role_has_exactly_one_target():
    roles = list(TARGET_TICKERS.values())
    assert sorted(roles) == sorted(TargetRole)


def test_the_bond_target_is_the_us_aggregate():
    # Decided 17 Sep 2026. The earlier exports were the Global Aggregate, a
    # different index and calendar, which must not be mistaken for the target.
    assert TARGET_TICKERS["LBUSTRUU Index"] is TargetRole.BOND
    assert "LEGATRUU Index" not in TARGET_TICKERS


def test_the_equity_target_is_the_s_and_p_500():
    assert TARGET_TICKERS["SPX Index"] is TargetRole.EQUITY


def test_the_preferred_field_is_total_return():
    # Both targets are forecast on a total-return basis, per the
    # validation-metrics document — never the plain price series.
    assert PREFERRED_FIELD == "TOT_RETURN_INDEX_GROSS_DVDS"
