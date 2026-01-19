from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any, Dict, List

import json

from utils import ensure_dir, utc_now_iso, atomic_write_json, date_utc_compact, retry
from calendar_client import fetch_fmp_calendar, normalize_currency, normalize_impact


@dataclass
class SourceStatus:
    ok: bool
    rows: int
    rows_total: int
    rows_filtered: int
    latest_time: str | None
    date_from: str
    date_to: str
    used_cache: bool
    error: str | None


def load_cache_json(path: Path) -> List[Dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def filter_events(
    events: List[Dict[str, Any]],
    currencies: List[str],
    impacts: List[str],
) -> List[Dict[str, Any]]:
    cur_set = {c.upper() for c in currencies if c}
    imp_set = {i.capitalize() for i in impacts if i}

    out: List[Dict[str, Any]] = []
    for e in events:
        cur = normalize_currency(e.get("currency"))
        imp = normalize_impact(e.get("impact"))

        if cur_set and cur not in cur_set:
            continue
        if imp_set and imp not in imp_set:
            continue

        # Keep a consistent set of fields + preserve raw
        out.append({
            "date": e.get("date"),          # FMP timezone is UTC :contentReference[oaicite:3]{index=3}
            "country": e.get("country"),
            "currency": cur,
            "event": e.get("event") or e.get("name"),
            "impact": imp,
            "actual": e.get("actual"),
            "forecast": e.get("forecast") or e.get("estimate"),
            "previous": e.get("previous"),
            "raw": e,
        })
    return out


def run_fetch_pipeline(cfg: Dict[str, Any], logger, base_dir: Path) -> Dict[str, Any]:
    data_dir = ensure_dir((base_dir / cfg["output"]["data_dir"]).resolve())

    run_tag = date_utc_compact()
    manifest_path_latest = data_dir / "fetch_manifest.json"
    manifest_path_archive = data_dir / f"fetch_manifest_{run_tag}.json"
    error_path_archive = data_dir / f"fetch_error_{run_tag}.json"

    snapshot_latest = data_dir / "calendar.json"                 # overwrite
    snapshot_daily = data_dir / f"calendar_{run_tag}.json"       # archive

    keep_run_manifest = cfg.get("output", {}).get("archive", {}).get("keep_run_manifest", True)
    keep_error_report = cfg.get("output", {}).get("archive", {}).get("keep_error_report", True)
    keep_daily_snapshot = cfg.get("output", {}).get("archive", {}).get("keep_daily_snapshot", True)

    cal_cfg = cfg.get("calendar", {}) or {}
    api_key = cal_cfg.get("api_key")
    timeout_seconds = int(cal_cfg.get("timeout_seconds", 30))

    lookback_days = int(cal_cfg.get("lookback_days", 3))
    forward_days = int(cal_cfg.get("forward_days", 21))
    currencies = cal_cfg.get("currencies", ["USD", "EUR"]) or ["USD", "EUR"]
    impacts = cal_cfg.get("impacts", ["High", "Medium"]) or ["High", "Medium"]

    attempts = int(cfg.get("retry", {}).get("attempts", 3))
    sleep_seconds = int(cfg.get("retry", {}).get("sleep_seconds", 2))

    # Use UTC date windows
    today_utc = datetime.now(timezone.utc).date()
    d_from: date = today_utc - timedelta(days=lookback_days)
    d_to: date = today_utc + timedelta(days=forward_days)

    status = SourceStatus(
        ok=False,
        rows=0,
        rows_total=0,
        rows_filtered=0,
        latest_time=None,
        date_from=d_from.strftime("%Y-%m-%d"),
        date_to=d_to.strftime("%Y-%m-%d"),
        used_cache=False,
        error=None,
    )

    events_raw: List[Dict[str, Any]] = []
    events_filtered: List[Dict[str, Any]] = []

    try:
        logger.info(f"Fetching calendar from FMP: {status.date_from} -> {status.date_to} (UTC)...")
        events_raw = retry(
            lambda: fetch_fmp_calendar(
                api_key=api_key,
                date_from=d_from,
                date_to=d_to,
                timeout_seconds=timeout_seconds,
            ),
            attempts=attempts,
            sleep_seconds=sleep_seconds,
            logger=logger,
            label="FMP_CALENDAR",
        )

        events_filtered = filter_events(events_raw, currencies=currencies, impacts=impacts)

        # Save snapshots
        atomic_write_json(snapshot_latest, events_filtered)
        if keep_daily_snapshot:
            atomic_write_json(snapshot_daily, events_filtered)

        status.ok = True
        status.rows_total = len(events_raw)
        status.rows_filtered = len(events_filtered)
        status.rows = len(events_filtered)
        status.latest_time = max(
            (e.get("date") for e in events_filtered if e.get("date")),
            default=None,
        )

        logger.info(f"Saved snapshot latest: {snapshot_latest} rows_filtered={len(events_filtered)}")
        if keep_daily_snapshot:
            logger.info(f"Saved snapshot daily: {snapshot_daily}")

    except Exception as e:
        logger.error(f"Calendar fetch failed: {e}")

        cache = load_cache_json(snapshot_latest)
        if cache is not None:
            events_filtered = cache
            status.ok = True
            status.used_cache = True
            status.error = str(e)
            status.rows_filtered = len(cache)
            status.rows = len(cache)
            status.latest_time = max(
                (item.get("date") for item in cache if isinstance(item, dict) and item.get("date")),
                default=None,
            )
            logger.warning("Using cache calendar.json (stale).")
        elif bool(cal_cfg.get("allow_empty_on_error", False)):
            events_filtered = []
            status.ok = True
            status.error = str(e)
            status.rows = 0
            status.rows_total = 0
            status.rows_filtered = 0
            status.latest_time = None
            atomic_write_json(snapshot_latest, events_filtered)
            if keep_daily_snapshot:
                atomic_write_json(snapshot_daily, events_filtered)
            logger.warning("Calendar fetch failed; wrote empty snapshot because allow_empty_on_error is enabled.")
        else:
            status.ok = False
            status.error = str(e)

        if keep_error_report:
            atomic_write_json(error_path_archive, {
                "asof_utc": utc_now_iso(),
                "stage": "fetch_calendar_fmp",
                "error": str(e),
            })

    notes = ""
    if not status.ok:
        notes = "Calendar fetch failed and no cache available."
    elif status.error and not status.used_cache:
        notes = "Calendar fetch failed; wrote empty snapshot."

    manifest = {
        "asof_utc": utc_now_iso(),
        "sources": {
            "FMP_ECONOMIC_CALENDAR": {
                **vars(status),
                "filters": {"currencies": currencies, "impacts": impacts},
            }
        },
        "stale_sources": (["FMP_ECONOMIC_CALENDAR"] if status.used_cache else []),
        "notes": notes,
    }

    atomic_write_json(manifest_path_latest, manifest)
    if keep_run_manifest:
        atomic_write_json(manifest_path_archive, manifest)

    logger.info(f"Wrote manifest latest: {manifest_path_latest}")
    if keep_run_manifest:
        logger.info(f"Wrote manifest archive: {manifest_path_archive}")

    return manifest
