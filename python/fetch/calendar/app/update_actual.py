from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from calendar_scrape_utils import (
    ART_DIR,
    bkk_now,
    fetch_calendar_htmls,
    merge_events,
    output_paths,
    parse_calendar_html,
    write_csv,
)


def pick_latest_weekly_json() -> Path | None:
    candidates = sorted(ART_DIR.glob("weekly_calendar_*_bkk.json"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Update actuals for weekly calendar events.")
    ap.add_argument("--in", dest="in_path", default="", help="Weekly calendar JSON path.")
    args = ap.parse_args()

    in_path = Path(args.in_path) if args.in_path else pick_latest_weekly_json()
    if not in_path or not in_path.exists():
        raise FileNotFoundError("Missing weekly calendar json. Provide --in path.")

    events = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(events, list):
        raise ValueError("Input JSON must be a list of events.")

    now = bkk_now()
    now_epoch = int(now.timestamp())
    tz = now.tzinfo
    dates_to_refresh = set()
    for e in events:
        try:
            epoch = int(e.get("dateline_epoch"))
        except Exception:
            continue
        actual = e.get("actual")
        if epoch <= now_epoch and (actual is None or str(actual).strip() == ""):
            dt_bkk = datetime.fromtimestamp(epoch, tz=tz)
            dates_to_refresh.add(dt_bkk.date())

    if not dates_to_refresh:
        print("No events need actual updates yet.")
        return

    results, errors = fetch_calendar_htmls(sorted(dates_to_refresh))
    updates: list[dict] = []
    for res in results:
        updates.extend(parse_calendar_html(res.html))

    merged, stats = merge_events(events, updates)

    json_path, csv_path = output_paths("weekly_calendar_actuals")
    json_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(merged, csv_path)

    print(f"OK matched: {stats['matched']}")
    print(f"OK updated_any: {stats['updated_any']}")
    print(f"OK updated_actual: {stats['updated_actual']}")
    print(f"OK json: {json_path.resolve()}")
    print(f"OK csv : {csv_path.resolve()}")
    if errors:
        print("WARN errors:")
        for err in errors:
            print("-", err)


if __name__ == "__main__":
    main()
