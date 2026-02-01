from __future__ import annotations

import json

from calendar_scrape_utils import (
    bkk_today,
    fetch_calendar_htmls,
    output_paths,
    parse_calendar_html,
    week_days,
    write_csv,
)


def main() -> None:
    days = week_days(bkk_today())
    results, errors = fetch_calendar_htmls(days)

    rows: list[dict] = []
    for res in results:
        rows.extend(parse_calendar_html(res.html))

    rows = [
        r
        for r in rows
        if str(r.get("currency") or "").upper() in {"EUR", "USD"}
    ]
    rows.sort(key=lambda r: (r["dateline_epoch"], r["event_id"]))

    json_path, csv_path = output_paths("weekly_calendar")
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(rows, csv_path)

    print(f"OK rows: {len(rows)}")
    print(f"OK json: {json_path.resolve()}")
    print(f"OK csv : {csv_path.resolve()}")
    if errors:
        print("WARN errors:")
        for err in errors:
            print("-", err)


if __name__ == "__main__":
    main()
