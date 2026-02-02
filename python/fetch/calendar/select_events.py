# python/fetch/calendar/select_events.py
#
# Purpose:
# - Read python/Data/raw_data/calendar/calendar_all_event.json
# - Filter events using config.yaml options
# - Output python/Data/raw_data/calendar/calendar_select_events.json (+ csv, meta)
#
# Notes:
# - ASCII-only console output (Windows cp1252 safe).

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils import load_config


# -----------------------
# Config
# -----------------------
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

ART_DIR = Path("python") / "Data" / "raw_data" / "calendar"

IN_EVENTS = ART_DIR / "calendar_all_event.json"
OUT_EVENTS_JSON = ART_DIR / "calendar_select_events.json"
OUT_EVENTS_CSV = ART_DIR / "calendar_select_events.csv"
OUT_META = ART_DIR / "select_events.meta.json"
OUT_ERR = ART_DIR / "select_events_error.txt"


def ensure_dirs() -> None:
    ART_DIR.mkdir(parents=True, exist_ok=True)


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    headers = list(rows[0].keys())

    def esc_csv(x: Any) -> str:
        s = "" if x is None else str(x)
        if any(c in s for c in [",", '"', "\n"]):
            s = '"' + s.replace('"', '""') + '"'
        return s

    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(headers) + "\n")
        for r in rows:
            f.write(",".join(esc_csv(r.get(h)) for h in headers) + "\n")


def load_events(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("calendar_all_event.json must be a list")
    return [row for row in data if isinstance(row, dict)]


def normalize_list(values: Any) -> list[str]:
    if not values:
        return []
    if isinstance(values, list):
        return [str(v).strip() for v in values if str(v).strip()]
    return [str(values).strip()] if str(values).strip() else []


def filter_events(events: list[dict], cfg: dict) -> list[dict]:
    filters = cfg.get("select_events", {}) or {}

    currencies = {c.upper() for c in normalize_list(filters.get("currencies"))}
    impacts = {i.lower() for i in normalize_list(filters.get("impacts"))}
    countries = {c.lower() for c in normalize_list(filters.get("countries"))}
    name_keywords = [k.lower() for k in normalize_list(filters.get("name_keywords"))]
    exclude_keywords = [k.lower() for k in normalize_list(filters.get("exclude_name_keywords"))]

    impact_score_min = filters.get("impact_score_min")
    if impact_score_min is not None:
        try:
            impact_score_min = int(impact_score_min)
        except Exception:
            impact_score_min = None

    out: list[dict] = []

    for e in events:
        currency = (e.get("currency") or "").upper().strip()
        impact = (e.get("impact") or "").lower().strip()
        country = (e.get("country") or "").lower().strip()
        name = (e.get("name") or "").lower().strip()

        if currencies and currency not in currencies:
            continue
        if impacts and impact not in impacts:
            continue
        if countries and country not in countries:
            continue
        if impact_score_min is not None:
            score = e.get("impact_score")
            try:
                score_val = int(score)
            except Exception:
                score_val = 0
            if score_val < impact_score_min:
                continue
        if name_keywords and not any(k in name for k in name_keywords):
            continue
        if exclude_keywords and any(k in name for k in exclude_keywords):
            continue

        out.append(e)

    return out


def main() -> None:
    ensure_dirs()

    if not IN_EVENTS.exists():
        raise FileNotFoundError("Missing input: " + str(IN_EVENTS.resolve()))

    cfg = load_config(str(CONFIG_PATH)) if CONFIG_PATH.exists() else {}

    events = load_events(IN_EVENTS)
    selected = filter_events(events, cfg)

    OUT_EVENTS_JSON.write_text(
        json.dumps(selected, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(selected, OUT_EVENTS_CSV)

    meta = {
        "generated_at_utc": iso_utc_now(),
        "input_events_json": str(IN_EVENTS.resolve()),
        "output_events_json": str(OUT_EVENTS_JSON.resolve()),
        "output_events_csv": str(OUT_EVENTS_CSV.resolve()),
        "selected_count": len(selected),
        "filters": cfg.get("select_events", {}) or {},
    }
    OUT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print("OK selected:", len(selected), flush=True)
    print("OK saved:", str(OUT_EVENTS_JSON.resolve()), flush=True)
    print("OK saved:", str(OUT_EVENTS_CSV.resolve()), flush=True)
    print("OK saved:", str(OUT_META.resolve()), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        ensure_dirs()
        OUT_ERR.write_text(traceback.format_exc(), encoding="utf-8")
        print("ERROR saved ->", str(OUT_ERR.resolve()), flush=True)
        input("Press Enter to exit...")
