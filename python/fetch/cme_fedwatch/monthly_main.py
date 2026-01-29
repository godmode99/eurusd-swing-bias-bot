from __future__ import annotations

import argparse
from pathlib import Path

from watchlist_filter import (
    DEFAULT_FILTERED_DIRS,
    DEFAULT_OUTPUT_DIR,
    FILTER_PREFIXES,
    build_filtered_watchlists,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter CME watchlist (monthly)")
    parser.add_argument(
        "--watchlist",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "watchlist.json",
        help="Path to watchlist.json",
    )
    args = parser.parse_args()

    watchlist_path = args.watchlist
    if not watchlist_path.exists():
        raise SystemExit(f"watchlist not found: {watchlist_path}")

    build_filtered_watchlists(
        watchlist_path,
        output_dirs={"monthly": DEFAULT_FILTERED_DIRS["monthly"]},
        prefix_map={"monthly": FILTER_PREFIXES["monthly"]},
    )


if __name__ == "__main__":
    main()
