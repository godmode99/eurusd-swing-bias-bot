from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = BASE_DIR.parents[2] / "Data" / "raw_data" / "cme"
DEFAULT_FILTERED_DIRS = {
    "daily": DEFAULT_OUTPUT_DIR / "daily",
    "weekly": DEFAULT_OUTPUT_DIR / "weekly",
    "monthly": DEFAULT_OUTPUT_DIR / "monthly",
}

FILTER_PREFIXES = {
    "daily": ["zq", "sr1", "sr3", "zt", "6e"],
    "weekly": ["zq", "sr1", "sr3", "zn", "6e", "zt", "zf", "zb"],
    "monthly": ["zq", "sr1", "sr3", "zn", "tn", "zb", "ub", "twe", "6e", "e7", "m6e"],
}


def normalize_code(value: str | None) -> str:
    return (value or "").strip()


def build_filtered_watchlists(
    json_path: Path,
    output_dirs: dict[str, Path] | None = None,
    prefix_map: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, int | str]]:
    output_dirs = output_dirs or DEFAULT_FILTERED_DIRS
    prefix_map = prefix_map or FILTER_PREFIXES

    try:
        raw_items = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"❌ read watchlist json failed: {exc}")
        return {}

    if not isinstance(raw_items, list):
        print("⚠️ watchlist json is not a list")
        return {}

    summaries: dict[str, dict[str, int | str]] = {}

    for cadence, prefixes in prefix_map.items():
        prefix_tuple = tuple(p.lower() for p in prefixes)
        filtered = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            code = normalize_code(item.get("Code"))
            if not code:
                continue
            if code.lower().startswith(prefix_tuple):
                filtered.append(item)

        out_dir = output_dirs.get(cadence, DEFAULT_OUTPUT_DIR / cadence)
        out_dir.mkdir(parents=True, exist_ok=True)

        main_path = out_dir / f"{cadence}_main.json"
        config_path = out_dir / f"{cadence}_config.json"

        unique_codes: list[str] = []
        seen_codes: set[str] = set()
        for item in filtered:
            code = normalize_code(item.get("Code")).upper()
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            unique_codes.append(code)

        config_payload = {
            "prefixes": [p.lower() for p in prefixes],
            "codes": unique_codes,
            "total_codes": len(unique_codes),
            "total_items": len(filtered),
        }

        with open(main_path, "w", encoding="utf-8") as f:
            json.dump(filtered, f, ensure_ascii=False, indent=2)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_payload, f, ensure_ascii=False, indent=2)

        summaries[cadence] = {
            "items": len(filtered),
            "codes": len(unique_codes),
            "main": str(main_path),
            "config": str(config_path),
        }

        print(f"✅ saved {cadence} watchlist: {main_path}")
        print(f"✅ saved {cadence} config: {config_path}")

    return summaries
