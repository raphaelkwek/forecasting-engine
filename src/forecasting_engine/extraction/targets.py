"""Which Bloomberg securities are forecast targets, and which role each plays.

Signals are open: any numeric column an export produces is screened generically,
so they need no mapping. Targets are the exception. There are exactly two, both
forecast on a total-return basis and never pooled, and target detection at
ingestion needs to recognise them by ticker.

Salvaged from ``ingest.bloomberg.TICKER_MAP`` when that fixed-contract module was
retired. That table mapped a ticker to a fixed column name
(``"SPX Index": "spx_close"``) for all seven contract signals; only the two
target entries carry over, reshaped from column name to role.

The bond target is ``LBUSTRUU Index``, the US Aggregate, decided 17 Sep 2026.
The team's earlier exports were ``LEGATRUU Index``, the *Global* Aggregate — a
different index on a different calendar, so it is deliberately not listed.
See ``docs/bloomberg-exports.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class TargetRole(StrEnum):
    EQUITY = "equity"
    BOND = "bond"


#: The ticker read from an export's ``Security`` metadata, mapped to the target
#: role it fills. Used as a pre-filled default at ingestion, never as a silent
#: final answer: the person uploading can override it.
TARGET_TICKERS: Mapping[str, TargetRole] = {
    "SPX Index": TargetRole.EQUITY,
    "LBUSTRUU Index": TargetRole.BOND,
}

#: Both targets are forecast on a total-return basis — dividends/coupons
#: reinvested — never the plain price series. Pre-filled default for which
#: field within a target export is the target series; overridable, since a
#: file can carry more than one field (e.g. PX_LAST alongside this one).
PREFERRED_FIELD = "TOT_RETURN_INDEX_GROSS_DVDS"
