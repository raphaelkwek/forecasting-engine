"""PBO (Probability of Backtest Overfitting) via Combinatorially Symmetric
Cross-Validation (CSCV).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

N_BLOCKS: int = 16
"""Working default (not sponsor-confirmed): number of contiguous blocks to
split history into. Must be even; 16 is the standard CSCV choice."""


@dataclass(frozen=True)
class PBOResult:
    """``configurations_tested`` is the CTQ-required traceability log —
    every configuration compared, not just the resulting score."""

    pbo: float
    configurations_tested: tuple[str, ...]
    n_combinations_tested: int


def compute_pbo(configs: Mapping[str, pd.Series], n_blocks: int = N_BLOCKS) -> PBOResult:
    """Probability that the best in-sample configuration in ``configs`` is
    just noise rather than a real edge.

    Splits history into ``n_blocks`` contiguous blocks and tries every way
    to call half of them in-sample. PBO is the share of those splits where
    the in-sample winner (by Sharpe) falls at or below the out-of-sample
    median.
    """
    if len(configs) < 2:
        raise ValueError("compute_pbo needs at least two configurations")
    if n_blocks % 2 != 0:
        raise ValueError(f"n_blocks must be even, got {n_blocks}")

    names = tuple(configs.keys())
    frame = pd.concat(configs.values(), axis=1, keys=names).dropna().sort_index()
    blocks = np.array_split(np.arange(len(frame)), n_blocks)
    half = n_blocks // 2

    below_median = 0
    n_combinations = 0
    for is_blocks in combinations(range(n_blocks), half):
        oos_blocks = [b for b in range(n_blocks) if b not in is_blocks]
        is_rows = np.concatenate([blocks[b] for b in is_blocks])
        oos_rows = np.concatenate([blocks[b] for b in oos_blocks])

        best_config = _sharpe(frame.iloc[is_rows]).idxmax()
        oos_rank = _sharpe(frame.iloc[oos_rows]).rank(pct=True)[best_config]

        if oos_rank <= 0.5:
            below_median += 1
        n_combinations += 1

    return PBOResult(
        pbo=below_median / n_combinations,
        configurations_tested=names,
        n_combinations_tested=n_combinations,
    )


def _sharpe(returns: pd.DataFrame) -> pd.Series:
    return returns.mean() / returns.std(ddof=1)
