"""Synthetic market data matching ``docs/data-specification.md``.

Exists so the pipeline can be built and tested before institutional exports are
available. The default output deliberately contains the defects the quality
checks are supposed to catch.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from forecasting_engine.ingest.schema import DATE_COLUMN

TRADING_DAYS_PER_YEAR = 252
_CRASH_LENGTH = 30


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

    vix = _volatility_path(rng, n, stress)
    daily_vol = vix / 100.0 / np.sqrt(TRADING_DAYS_PER_YEAR)

    equity_returns = rng.normal(0.0, 1.0, n) * daily_vol + 0.0003 - 0.012 * stress
    bond_returns = rng.normal(0.0001, 0.0025, n) + 0.002 * stress

    frame = pd.DataFrame(
        {
            DATE_COLUMN: dates,
            "spx_close": 3000.0 * np.exp(np.cumsum(equity_returns)),
            "agg_close": 100.0 * np.exp(np.cumsum(bond_returns)),
            "vix": vix,
            "credit_spread_hy": np.clip(
                3.5 + 0.12 * (vix - 16.0) + rng.normal(0, 0.08, n), 0.5, None
            ),
            "credit_spread_ig": np.clip(
                1.2 + 0.03 * (vix - 16.0) + rng.normal(0, 0.03, n), 0.2, None
            ),
            "fx_impl_vol": np.clip(8.0 + 0.25 * (vix - 16.0) + rng.normal(0, 0.3, n), 2.0, None),
            "breakeven_10y": 2.2 + np.cumsum(rng.normal(0, 0.004, n)),
            "term_spread": 1.0 + np.cumsum(rng.normal(0, 0.005, n)),
        }
    )
    return _inject_defects(frame) if with_defects else frame


def _volatility_path(rng: np.random.Generator, n: int, stress: np.ndarray) -> np.ndarray:
    """Mean-reverting VIX around 16, spiking through the stress window."""
    vix = np.empty(n)
    vix[0] = 16.0
    for i in range(1, n):
        shock = rng.normal(0.0, 1.1) + 8.0 * stress[i]
        vix[i] = max(9.0, vix[i - 1] + 0.06 * (16.0 - vix[i - 1]) + 0.35 * shock)
    return vix


def _inject_defects(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the flaws a real vendor export has, so the quality checks earn their keep.

    Positions are relative to the sample length so a one-year file gets the same
    treatment as a ten-year one.
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
    parser = argparse.ArgumentParser(description="Generate synthetic signal data.")
    parser.add_argument("--years", type=int, default=10, help="years of history (default: 10)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42)")
    parser.add_argument("--out", type=Path, default=Path("data/raw/signals.csv"))
    parser.add_argument("--clean", action="store_true", help="omit the deliberate defects")
    args = parser.parse_args(argv)

    frame = generate(years=args.years, seed=args.seed, with_defects=not args.clean)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False)
    print(f"wrote {len(frame)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
