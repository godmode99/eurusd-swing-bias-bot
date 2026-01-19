from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any

import pandas as pd

from utils import ensure_dir, utc_now_iso, atomic_write_json, date_utc_compact, retry
from fred_client import fetch_fred_series_observations


@dataclass
class SourceStatus:
    ok: bool
    rows: int
    latest_date: str | None
    used_cache: bool
    error: str | None


def load_cache_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def save_csv(df: pd.DataFrame, path: Path) -> None:
    # overwrite always (ตาม policy)
    out = df.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(path, index=False)


def run_fetch_pipeline(cfg: Dict[str, Any], logger, base_dir: Path) -> Dict[str, Any]:
    """
    Policy:
      - data CSV overwrite: raw_data_macro/us2y_dgs2.csv
      - latest manifest overwrite: fetch_manifest.json
      - archive manifest dated: fetch_manifest_YYYYMMDD.json
      - error report dated on failures: fetch_error_YYYYMMDD.json
    """
    data_dir = ensure_dir((base_dir / cfg["output"]["data_dir"]).resolve())

    run_tag = date_utc_compact()
    manifest_path_latest = data_dir / "fetch_manifest.json"
    manifest_path_archive = data_dir / f"fetch_manifest_{run_tag}.json"
    error_path_archive = data_dir / f"fetch_error_{run_tag}.json"

    keep_run_manifest = cfg.get("output", {}).get("archive", {}).get("keep_run_manifest", True)
    keep_error_report = cfg.get("output", {}).get("archive", {}).get("keep_error_report", True)

    fred_cfg = cfg.get("fred", {}) or {}
    series_id = fred_cfg.get("series_id", "DGS2")
    api_key = fred_cfg.get("api_key")
    observation_start = fred_cfg.get("observation_start", "2010-01-01")
    timeout_seconds = int(fred_cfg.get("timeout_seconds", 30))

    attempts = int(cfg.get("retry", {}).get("attempts", 3))
    sleep_seconds = int(cfg.get("retry", {}).get("sleep_seconds", 2))

    out_csv = data_dir / "us2y_dgs2.csv"

    status = SourceStatus(ok=False, rows=0, latest_date=None, used_cache=False, error=None)

    try:
        logger.info(f"Fetching FRED series {series_id} from {observation_start}...")
        df = retry(
            lambda: fetch_fred_series_observations(
                series_id=series_id,
                api_key=api_key,
                observation_start=observation_start,
                timeout_seconds=timeout_seconds,
            ),
            attempts=attempts,
            sleep_seconds=sleep_seconds,
            logger=logger,
            label=f"FRED_{series_id}",
        )

        if df.empty:
            raise RuntimeError("FRED dataframe empty after fetch")

        latest_date = df["date"].iloc[-1].strftime("%Y-%m-%d")
        save_csv(df, out_csv)  # overwrite
        status = SourceStatus(ok=True, rows=len(df), latest_date=latest_date, used_cache=False, error=None)

        logger.info(f"Saved {out_csv} rows={len(df)} latest_date={latest_date}")

    except Exception as e:
        logger.error(f"Fetch FRED {series_id} failed: {e}")

        cache_df = load_cache_csv(out_csv)
        if cache_df is not None and len(cache_df) > 0:
            latest_date = pd.to_datetime(cache_df["date"].iloc[-1]).strftime("%Y-%m-%d")
            status = SourceStatus(ok=True, rows=len(cache_df), latest_date=latest_date, used_cache=True, error=str(e))
            logger.warning("Using cache for FRED (stale).")
        else:
            status = SourceStatus(ok=False, rows=0, latest_date=None, used_cache=False, error=str(e))

        if keep_error_report:
            atomic_write_json(error_path_archive, {
                "asof_utc": utc_now_iso(),
                "stage": f"fetch_fred_{series_id}",
                "error": str(e),
            })

    manifest = {
        "asof_utc": utc_now_iso(),
        "sources": {
            f"FRED_{series_id}": {
                **vars(status)
            }
        },
        "stale_sources": (["FRED_" + series_id] if status.used_cache else []),
        "notes": "" if status.ok else "FRED fetch failed and no cache available.",
    }

    atomic_write_json(manifest_path_latest, manifest)
    if keep_run_manifest:
        atomic_write_json(manifest_path_archive, manifest)

    logger.info(f"Wrote manifest latest: {manifest_path_latest}")
    if keep_run_manifest:
        logger.info(f"Wrote manifest archive: {manifest_path_archive}")

    return manifest
