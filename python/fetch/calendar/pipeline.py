# python/fetch/calendar/pipeline.py
#
# Purpose:
# - Run calendar fetch pipeline steps based on config.yaml flags.

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from utils import load_config


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

DEFAULT_STEPS = {
    "01_save_session": False,
    "02_capture_document_html": True,
    "03_extract_from_document": True,
    "select_events": True,
    "20_make_risk_windows": False,
    "30_refresh_actuals": False,
    "40_compute_surprise": False,
}


def load_steps() -> dict[str, bool]:
    cfg = load_config(str(CONFIG_PATH)) if CONFIG_PATH.exists() else {}
    pipeline_cfg = cfg.get("pipeline", {}) or {}
    steps_cfg = pipeline_cfg.get("steps", {}) or {}
    steps: dict[str, bool] = {}
    for name, default in DEFAULT_STEPS.items():
        value = steps_cfg.get(name, default)
        steps[name] = bool(value)
    return steps


def run_step(name: str) -> None:
    script_path = SCRIPT_DIR / f"{name}.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Missing step script: {script_path}")
    subprocess.run([sys.executable, str(script_path)], check=True)


def main() -> None:
    steps = load_steps()
    for name, enabled in steps.items():
        if not enabled:
            print(f"SKIP {name}")
            continue
        print(f"RUN  {name}")
        run_step(name)


if __name__ == "__main__":
    main()
