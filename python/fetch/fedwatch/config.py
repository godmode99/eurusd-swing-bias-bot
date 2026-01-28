from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_AUTH_URL = "https://login.cmegroup.com/sso/accountstatus/showAuth.action"
DEFAULT_WATCHLIST_URL = "https://www.cmegroup.com/watchlists/details.1769586889025783750.C.html"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "Data" / "raw_data" / "cme"
NAV_TIMEOUT = 60_000


def load_config() -> dict:
    cfg_path = Path(__file__).with_name("config.json")
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def resolve_output_paths(cfg: dict) -> dict[str, Path]:
    output_dir = Path(cfg.get("watchlist_output_dir", DEFAULT_OUTPUT_DIR))
    output_dir.mkdir(parents=True, exist_ok=True)

    html_output = Path(cfg.get("watchlist_output", output_dir / "watchlist.html"))
    json_output = Path(cfg.get("watchlist_json_output", output_dir / "watchlist.json"))
    csv_output = Path(cfg.get("watchlist_csv_output", output_dir / "watchlist.csv"))

    if not html_output.is_absolute():
        html_output = output_dir / html_output
    if not json_output.is_absolute():
        json_output = output_dir / json_output
    if not csv_output.is_absolute():
        csv_output = output_dir / csv_output

    return {
        "output_dir": output_dir,
        "html_output": html_output,
        "json_output": json_output,
        "csv_output": csv_output,
    }


def resolve_user_data_dir(cfg: dict) -> str:
    return (cfg.get("user_data_dir") or os.environ.get("CME_USER_DATA_DIR") or "cme_profile").strip()
