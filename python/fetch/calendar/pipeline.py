# python/fetch/calendar/pipeline.py
#
# Purpose:
# - Run calendar fetch pipeline steps based on config.yaml flags.

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent.resolve()
PYTHON_DIR = BASE_DIR.parents[1].resolve()
TELEGRAM_REPORT_DIR = PYTHON_DIR / "telegram_report"

if TELEGRAM_REPORT_DIR.exists() and str(TELEGRAM_REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(TELEGRAM_REPORT_DIR))

if not (TELEGRAM_REPORT_DIR / "telegram_notifier.py").exists():
    raise FileNotFoundError(
        f"telegram_notifier.py not found at: {TELEGRAM_REPORT_DIR / 'telegram_notifier.py'}\n"
        f"BASE_DIR={BASE_DIR}\n"
        f"PYTHON_DIR={PYTHON_DIR}\n"
        f"TELEGRAM_REPORT_DIR={TELEGRAM_REPORT_DIR}"
    )

from telegram_notifier import send_telegram_message

from utils import load_config, setup_logger, utc_now_iso


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


def format_pipeline_message(status: str, results: list[dict[str, Any]], error: str | None) -> str:
    if status == "OK":
        head = "✅ <b>Calendar Fetch: OK</b>"
    else:
        head = "❌ <b>Calendar Fetch: ERROR</b>"

    lines = [head, f"<b>asof_utc</b>: {utc_now_iso()}"]
    if results:
        lines.append("<b>Steps</b>:")
        for item in results:
            name = item["name"]
            outcome = item["status"]
            tag = "OK" if outcome == "success" else "FAIL"
            lines.append(f"• {name}: {tag}")
    if error:
        lines.append(f"<b>error</b>: {error}")
    return "\n".join(lines)


def main() -> None:
    steps = load_steps()
    cfg = load_config(str(CONFIG_PATH)) if CONFIG_PATH.exists() else {}
    logs_dir = (SCRIPT_DIR / cfg.get("output", {}).get("logs_dir", "logs")).resolve()
    logger = setup_logger(logs_dir, name="fetch_calendar")

    results: list[dict[str, Any]] = []
    error_message: str | None = None

    logger.info("=== CALENDAR PIPELINE START ===")
    for name, enabled in steps.items():
        if not enabled:
            logger.info("SKIP %s", name)
            continue
        logger.info("RUN  %s", name)
        try:
            run_step(name)
            results.append({"name": name, "status": "success"})
        except Exception as exc:
            error_message = str(exc)
            results.append({"name": name, "status": "failed"})
            logger.exception("Step failed: %s", name)
            break
    logger.info("=== CALENDAR PIPELINE END ===")

    status = "ERROR" if error_message else "OK"
    tg = cfg.get("telegram", {}) or {}
    send_ok = bool(tg.get("send_on_success", True))
    send_err = bool(tg.get("send_on_error", True))
    should_send = (status == "OK" and send_ok) or (status == "ERROR" and send_err)
    if should_send:
        message = format_pipeline_message(status, results, error_message)
        send_telegram_message(cfg, message, logger=logger)

    if error_message:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
