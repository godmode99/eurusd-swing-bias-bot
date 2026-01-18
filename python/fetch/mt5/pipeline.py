# pipeline.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd

from fetch_mt5 import MT5Client
from utils import ensure_dir, utc_now_iso, atomic_write_json, date_utc_compact


@dataclass
class SourceStatus:
    ok: bool
    rows: int
    latest_time: str | None
    used_cache: bool
    error: str | None


def validate_ohlc(df: pd.DataFrame, cfg: Dict[str, Any]) -> None:
    if df.empty:
        raise ValueError("OHLC dataframe is empty")

    min_price = float(cfg["validation"]["min_price"])
    max_price = float(cfg["validation"]["max_price"])
    max_missing_ratio = float(cfg["validation"]["max_missing_ratio"])

    for c in ["open", "high", "low", "close"]:
        miss = float(df[c].isna().mean())
        if miss > max_missing_ratio:
            raise ValueError(f"Too many missing values in {c}: {miss:.4f} > {max_missing_ratio}")
        if (df[c] <= 0).any():
            raise ValueError(f"Non-positive prices in {c}")
        if (df[c] < min_price).any() or (df[c] > max_price).any():
            raise ValueError(f"Price out of range in {c} (expected {min_price}..{max_price})")

    # OHLC containment
    if not ((df["low"] <= df["open"]) & (df["open"] <= df["high"])).all():
        raise ValueError("OHLC containment failed for open")
    if not ((df["low"] <= df["close"]) & (df["close"] <= df["high"])).all():
        raise ValueError("OHLC containment failed for close")

    # time monotonic
    if not df["time_utc"].is_monotonic_increasing:
        raise ValueError("time_utc is not sorted increasing")


def load_cache_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "time_utc" in df.columns:
        df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    return df


def save_csv(df: pd.DataFrame, path: Path) -> None:
    """
    Always overwrites OHLC files (as requested). We store time_utc as ISO-Z string.
    """
    out = df.copy()
    out["time_utc"] = out["time_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out.to_csv(path, index=False)


def run_fetch_pipeline(cfg: Dict[str, Any], logger, base_dir: Path) -> Dict[str, Any]:
    """
    Policy:
      - OHLC CSVs overwrite (eurusd_d1.csv, eurusd_h4.csv)
      - Latest manifest overwrites (fetch_manifest.json)
      - Run manifest archived with date suffix (fetch_manifest_YYYYMMDD.json)
      - Error report archived with date suffix on failures (fetch_error_YYYYMMDD.json)
    """
    # Resolve output dirs relative to the folder containing main.py/config.yaml
    data_dir = ensure_dir((base_dir / cfg["output"]["data_dir"]).resolve())

    run_tag = date_utc_compact()  # YYYYMMDD (UTC)

    # Manifests
    manifest_path_latest = data_dir / "fetch_manifest.json"                 # overwrite
    manifest_path_archive = data_dir / f"fetch_manifest_{run_tag}.json"     # keep
    error_path_archive = data_dir / f"fetch_error_{run_tag}.json"           # keep on failure

    keep_run_manifest = cfg.get("output", {}).get("archive", {}).get("keep_run_manifest", True)
    keep_error_report = cfg.get("output", {}).get("archive", {}).get("keep_error_report", True)

    terminal_path = cfg["mt5"].get("terminal_path") or None
    symbols: List[str] = cfg.get("symbols", ["EURUSD"])
    bars_d1 = int(cfg["fetch"]["bars_d1"])
    bars_h4 = int(cfg["fetch"]["bars_h4"])
    store_time_as_utc = bool(cfg["fetch"].get("store_time_as_utc", True))

    mt5c = MT5Client(terminal_path=terminal_path)
    stale_sources: List[str] = []
    statuses: Dict[str, SourceStatus] = {}

    # --- CONNECT ---
    try:
        logger.info("Connecting to MT5...")
        mt5c.connect()
        logger.info("MT5 connected.")
    except Exception as e:
        logger.error(f"MT5 connect failed: {e}")
        try:
            mt5c.shutdown()
        except Exception:
            pass

        # Fallback to cache for each symbol/timeframe
        for sym in symbols:
            for tf, fname in [("D1", f"{sym.lower()}_d1.csv"), ("H4", f"{sym.lower()}_h4.csv")]:
                cache_path = data_dir / fname
                cache_df = load_cache_csv(cache_path)
                key = f"{sym}_{tf}"
                if cache_df is not None and len(cache_df) > 0:
                    latest = pd.to_datetime(cache_df["time_utc"].iloc[-1], utc=True).strftime("%Y-%m-%dT%H:%M:%SZ")
                    statuses[key] = SourceStatus(ok=True, rows=len(cache_df), latest_time=latest, used_cache=True, error=str(e))
                    stale_sources.append(key)
                else:
                    statuses[key] = SourceStatus(ok=False, rows=0, latest_time=None, used_cache=False, error=str(e))

        manifest = {
            "asof_utc": utc_now_iso(),
            "sources": {k: vars(v) for k, v in statuses.items()},
            "stale_sources": stale_sources,
            "notes": "MT5 connect failed; used cache where available.",
        }

        # Write latest + archive manifest
        atomic_write_json(manifest_path_latest, manifest)
        if keep_run_manifest:
            atomic_write_json(manifest_path_archive, manifest)

        # Write error report (dated)
        if keep_error_report:
            atomic_write_json(error_path_archive, {
                "asof_utc": utc_now_iso(),
                "stage": "connect_mt5",
                "error": str(e),
            })

        return manifest

    # --- FETCH ---
    for sym in symbols:
        # D1
        d1_path = data_dir / f"{sym.lower()}_d1.csv"
        try:
            logger.info(f"Fetching {sym} D1 ({bars_d1} bars)...")
            res = mt5c.fetch_rates(sym, "D1", bars_d1, store_time_as_utc=store_time_as_utc)
            validate_ohlc(res.df, cfg)
            save_csv(res.df, d1_path)  # overwrite
            statuses[f"{sym}_D1"] = SourceStatus(ok=True, rows=res.rows, latest_time=res.latest_time_utc, used_cache=False, error=None)
            logger.info(f"Saved {d1_path} rows={res.rows} latest={res.latest_time_utc}")
        except Exception as e:
            logger.error(f"Fetch {sym} D1 failed: {e}")
            cache_df = load_cache_csv(d1_path)
            if cache_df is not None and len(cache_df) > 0:
                latest = pd.to_datetime(cache_df["time_utc"].iloc[-1], utc=True).strftime("%Y-%m-%dT%H:%M:%SZ")
                statuses[f"{sym}_D1"] = SourceStatus(ok=True, rows=len(cache_df), latest_time=latest, used_cache=True, error=str(e))
                stale_sources.append(f"{sym}_D1")
                logger.warning(f"Using cache for {sym} D1 (stale).")
                if keep_error_report:
                    atomic_write_json(error_path_archive, {
                        "asof_utc": utc_now_iso(),
                        "stage": f"fetch_{sym}_D1",
                        "error": str(e),
                    })
            else:
                statuses[f"{sym}_D1"] = SourceStatus(ok=False, rows=0, latest_time=None, used_cache=False, error=str(e))
                if keep_error_report:
                    atomic_write_json(error_path_archive, {
                        "asof_utc": utc_now_iso(),
                        "stage": f"fetch_{sym}_D1",
                        "error": str(e),
                    })

        # H4
        h4_path = data_dir / f"{sym.lower()}_h4.csv"
        try:
            logger.info(f"Fetching {sym} H4 ({bars_h4} bars)...")
            res = mt5c.fetch_rates(sym, "H4", bars_h4, store_time_as_utc=store_time_as_utc)
            validate_ohlc(res.df, cfg)
            save_csv(res.df, h4_path)  # overwrite
            statuses[f"{sym}_H4"] = SourceStatus(ok=True, rows=res.rows, latest_time=res.latest_time_utc, used_cache=False, error=None)
            logger.info(f"Saved {h4_path} rows={res.rows} latest={res.latest_time_utc}")
        except Exception as e:
            logger.error(f"Fetch {sym} H4 failed: {e}")
            cache_df = load_cache_csv(h4_path)
            if cache_df is not None and len(cache_df) > 0:
                latest = pd.to_datetime(cache_df["time_utc"].iloc[-1], utc=True).strftime("%Y-%m-%dT%H:%M:%SZ")
                statuses[f"{sym}_H4"] = SourceStatus(ok=True, rows=len(cache_df), latest_time=latest, used_cache=True, error=str(e))
                stale_sources.append(f"{sym}_H4")
                logger.warning(f"Using cache for {sym} H4 (stale).")
                if keep_error_report:
                    atomic_write_json(error_path_archive, {
                        "asof_utc": utc_now_iso(),
                        "stage": f"fetch_{sym}_H4",
                        "error": str(e),
                    })
            else:
                statuses[f"{sym}_H4"] = SourceStatus(ok=False, rows=0, latest_time=None, used_cache=False, error=str(e))
                if keep_error_report:
                    atomic_write_json(error_path_archive, {
                        "asof_utc": utc_now_iso(),
                        "stage": f"fetch_{sym}_H4",
                        "error": str(e),
                    })

    # Shutdown MT5 cleanly
    try:
        mt5c.shutdown()
    except Exception:
        pass

    # --- MANIFEST WRITE ---
    manifest = {
        "asof_utc": utc_now_iso(),
        "sources": {k: vars(v) for k, v in statuses.items()},
        "stale_sources": stale_sources,
        "notes": "",
    }

    # Always overwrite latest manifest
    atomic_write_json(manifest_path_latest, manifest)
    # Archive manifest with date suffix
    if keep_run_manifest:
        atomic_write_json(manifest_path_archive, manifest)

    logger.info(f"Wrote manifest latest: {manifest_path_latest}")
    if keep_run_manifest:
        logger.info(f"Wrote manifest archive: {manifest_path_archive}")

    return manifest
