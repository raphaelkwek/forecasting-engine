"""Command line entry point for converting Bloomberg exports.

    uv run python -m forecasting_engine.convert path/to/*.xlsx -o signals.csv

Writes the CSV and prints what it did, including any signal it could not
supply. It exits non-zero when the result would not pass schema validation, so
it is safe to chain, but it still writes the file — a partial file you can look
at beats no file and a message.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forecasting_engine.ingest.bloomberg import DEFAULT_FIELD, convert


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = [Path(p) for p in args.files]

    missing = [p for p in paths if not p.is_file()]
    if missing:
        print("No such file: " + ", ".join(str(p) for p in missing), file=sys.stderr)
        return 2

    frame, report = convert(paths, field=args.field)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False)

    print(f"{args.out}")
    print(report.describe())
    if not report.complete:
        print("\nThis file will not pass validation yet. Fix the items above.", file=sys.stderr)
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m forecasting_engine.convert",
        description="Join Bloomberg terminal exports into one contract-shaped CSV.",
    )
    parser.add_argument("files", nargs="+", help="Bloomberg .xlsx exports")
    parser.add_argument(
        "-o", "--out", type=Path, default=Path("signals.csv"), help="where to write the CSV"
    )
    parser.add_argument(
        "--field",
        default=DEFAULT_FIELD,
        help=f"column to read from each Data sheet [{DEFAULT_FIELD}]",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
