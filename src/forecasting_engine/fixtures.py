"""Synthetic market data matching ``docs/data-specification.md``.

Exists so the pipeline can be built, tested and demonstrated before the
institutional exports are complete. The default output deliberately contains
the defects the quality checks are supposed to catch, because a file with
nothing wrong with it demonstrates nothing about the checks.

**This data is invented.** It is shaped to look plausible — a mean-reverting
volatility index, spreads that widen when it spikes, a stress window a third of
the way through — but no number in it came from a market. Anything generated
here is for exercising the software, never for analysis, and never to stand in
for real data in a result anyone might act on. The CLI says so on every run and
the filename it writes says so too.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from forecasting_engine.ingest.schema import DATE_COLUMN

TRADING_DAYS_PER_YEAR = 252

#: Under ``data/``, which is gitignored, and named so nobody mistakes it for an
#: export.
DEFAULT_OUT = Path("data/synthetic-signals.csv")

_CRASH_LENGTH = 30

#: Decimal places per column, matching what a Bloomberg export actually carries.
#: Full float precision would be both unrealistic and four times the file size.
_PRECISION = {
    "spx_close": 2,
    "spx_close_target": 2,
    "bond_index_global_agg": 4,
    "bond_index_target": 4,
    "vix": 2,
    "tnx_close": 4,
    "dollar_index": 3,
    "eur_fx_vol": 3,
    "credit_spread_ig": 3,
    "credit_spread_hy": 2,
    "breakeven_5y": 4,
    "breakeven_10y": 4,
    "term_spread": 4,
    "fx_impl_vol": 2,
    "ff_mkt_rf": 4,
    "ff_smb": 4,
    "ff_hml": 4,
    "ff_rmw": 4,
    "ff_cma": 4,
    "ff_rf": 4,
}

BANNER = "SYNTHETIC DATA — invented for testing and demos, not for analysis."


def generate(years: int = 10, seed: int = 42, *, with_defects: bool = True) -> pd.DataFrame:
    """Build a synthetic signal file.

    A stress window sits one third of the way through the sample so crash-recall
    labels and drawdown metrics have something real to find.
    """
    rng = np.random.default_rng(seed)
    n = years * TRADING_DAYS_PER_YEAR
    dates = pd.bdate_range(end=pd.Timestamp("2025-12-31"), periods=n)

    stress = np.zeros(n)
    crash_start = n // 3
    stress[crash_start : crash_start + _CRASH_LENGTH] = 1.0

    # One shock drives both, with opposite signs. Drawing them independently
    # would give a VIX whose level scales equity volatility but whose movements
    # are uncorrelated with returns — no leverage effect, and so almost nothing
    # for a model to learn. Real markets sit near -0.7.
    shocks = rng.normal(0.0, 1.0, n)

    vix = _volatility_path(rng, n, stress, shocks)
    daily_vol = vix / 100.0 / np.sqrt(TRADING_DAYS_PER_YEAR)

    equity_returns = shocks * daily_vol + 0.0003 - 0.012 * stress
    bond_returns = rng.normal(0.0001, 0.0025, n) + 0.002 * stress

    frame = pd.DataFrame(
        {
            DATE_COLUMN: dates,
            "spx_close": 3000.0 * np.exp(np.cumsum(equity_returns)),
            # Unlagged observed levels, mirroring the extraction output: the
            # target return a model learns is built from consecutive levels.
            "spx_close_target": 3000.0 * np.exp(np.cumsum(equity_returns)),
            "bond_index_global_agg": 100.0 * np.exp(np.cumsum(bond_returns)),
            "bond_index_target": 100.0 * np.exp(np.cumsum(bond_returns)),
            "vix": vix,
            "tnx_close": np.clip(4.0 + np.cumsum(rng.normal(0, 0.01, n)), 0.5, 15.0),
            "dollar_index": np.clip(100.0 + np.cumsum(rng.normal(0, 0.05, n)), 60.0, 160.0),
            "eur_fx_vol": np.clip(9.0 + 0.15 * (vix - 16.0) + rng.normal(0, 0.4, n), 1.0, None),
            "credit_spread_ig": np.clip(
                1.2 + 0.03 * (vix - 16.0) + _drift(rng, n, 0.008) + rng.normal(0, 0.05, n),
                0.3,
                None,
            ),
            # The high-yield spread tracks volatility but drifts on its own too.
            # Driving it from the VIX alone makes it a near-copy (r > 0.99),
            # which is neither realistic nor useful for signal screening.
            "credit_spread_hy": np.clip(
                2.0 + 0.05 * (vix - 16.0) + _drift(rng, n, 0.012) + rng.normal(0, 0.06, n),
                0.5,
                None,
            ),
            "breakeven_5y": 2.0 + np.cumsum(rng.normal(0, 0.004, n)),
            "breakeven_10y": 2.2 + np.cumsum(rng.normal(0, 0.004, n)),
            "term_spread": 1.0 + np.cumsum(rng.normal(0, 0.005, n)),
            "fx_impl_vol": np.clip(
                8.0 + 0.18 * (vix - 16.0) + _drift(rng, n, 0.030) + rng.normal(0, 0.35, n),
                2.0,
                None,
            ),
            # Fama-French 5-Factor daily returns (percent).
            # Mkt-RF tracks the equity excess return; the other factors are
            # independent for synthetic purposes.
            "ff_mkt_rf": equity_returns * 100.0,
            "ff_smb": rng.normal(0.02, 0.5, n),
            "ff_hml": rng.normal(0.01, 0.4, n),
            "ff_rmw": rng.normal(0.02, 0.3, n),
            "ff_cma": rng.normal(0.01, 0.3, n),
            "ff_rf": rng.normal(0.01, 0.01, n),
        }
    )

    frame = frame.round(_PRECISION)
    return _inject_defects(frame) if with_defects else frame


def _drift(rng: np.random.Generator, n: int, scale: float) -> np.ndarray:
    """A slow random walk, so a series has a life of its own beyond the VIX."""
    return np.cumsum(rng.normal(0.0, scale, n))


def _volatility_path(
    rng: np.random.Generator, n: int, stress: np.ndarray, shocks: np.ndarray
) -> np.ndarray:
    """Mean-reverting VIX around 16, spiking through the stress window.

    ``shocks`` is the same daily shock that drives equity returns, entering with
    a negative sign: volatility rises on the days prices fall.
    """
    vix = np.empty(n)
    vix[0] = 16.0
    for i in range(1, n):
        shock = -1.15 * shocks[i] + rng.normal(0.0, 0.85) + 8.0 * stress[i]
        vix[i] = max(9.0, vix[i - 1] + 0.06 * (16.0 - vix[i - 1]) + 0.35 * shock)
    return vix


def _inject_defects(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the flaws a real vendor export has, so the quality checks earn their keep.

    Positions are relative to the sample length so a one-year file gets the same
    treatment as a ten-year one. Every defect here is one the contract treats as
    reportable rather than fatal — the file still validates, and the quality
    report has something to show.
    """
    frame = frame.copy()
    n = len(frame)

    gap_start = n // 2
    frame = frame.drop(frame.index[gap_start : gap_start + 4])

    duplicated = frame.iloc[sorted({n // 12, n // 3, (2 * n) // 3})]
    frame = pd.concat([frame, duplicated]).sort_values(DATE_COLUMN).reset_index(drop=True)

    blank_start = n // 6
    for offset, column in enumerate(("vix", "credit_spread_hy", "fx_impl_vol")):
        frame.loc[blank_start + offset, column] = np.nan
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m forecasting_engine.fixtures",
        description=f"Generate synthetic signal data. {BANNER}",
    )
    parser.add_argument("--years", type=int, default=10, help="years of history (default: 10)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"[{DEFAULT_OUT}]")
    parser.add_argument("--clean", action="store_true", help="omit the deliberate defects")
    args = parser.parse_args(argv)

    frame = generate(years=args.years, seed=args.seed, with_defects=not args.clean)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False)
    print(f"wrote {len(frame):,} rows to {args.out}")
    print(BANNER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
