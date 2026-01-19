from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()            # .../python/fetch/calendar
PYTHON_DIR = BASE_DIR.parents[1].resolve()           # .../python
TELEGRAM_REPORT_DIR = PYTHON_DIR / "telegram_report"

if TELEGRAM_REPORT_DIR.exists() and str(TELEGRAM_REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(TELEGRAM_REPORT_DIR))

from telegram_notifier import (
    send_telegram_message,
    format_manifest_message,
    classify_manifest,
)

from utils import load_config, setup_logger
from pipeline import run_fetch_pipeline


def main():
    cfg_path = BASE_DIR / "config.yaml"
    cfg = load_config(str(cfg_path))

    logs_dir = (BASE_DIR / cfg["output"]["logs_dir"]).resolve()
    logger = setup_logger(logs_dir, name="fetch_calendar")

    logger.info("=== CALENDAR FETCH PIPELINE START ===")
    manifest = run_fetch_pipeline(cfg, logger, base_dir=BASE_DIR)
    logger.info("=== CALENDAR FETCH PIPELINE END ===")

    tg = cfg.get("telegram", {}) or {}
    status = classify_manifest(manifest)

    send_ok = bool(tg.get("send_on_success", True))
    send_warn = bool(tg.get("send_on_warning", True))
    send_err = bool(tg.get("send_on_error", True))

    should_send = (status == "OK" and send_ok) or (status == "WARN" and send_warn) or (status == "ERROR" and send_err)
    if should_send:
        msg = format_manifest_message(manifest).replace("MT5 Fetch", "Calendar Fetch")
        # token เผื่อมึงตั้ง env ไว้
        if not tg.get("bot_token"):
            tg["bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN")
        send_telegram_message(cfg, msg, logger=logger)


if __name__ == "__main__":
    main()
