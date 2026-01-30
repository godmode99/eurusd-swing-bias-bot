from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import requests

FEDWATCH_URL = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html?utm_source=chatgpt.com"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "Data" / "raw_data" / "cme" / "fedwatch_probabilities"
TIMEOUT_SECONDS = 30


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("cme_fedwatch_probabilities")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    response = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def save_html(html: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    snapshot_path = output_dir / f"fedwatch_probabilities_{timestamp}.html"
    latest_path = output_dir / "latest.html"
    snapshot_path.write_text(html, encoding="utf-8")
    latest_path.write_text(html, encoding="utf-8")
    return snapshot_path


def main() -> None:
    logger = setup_logger()
    logger.info("Fetching CME FedWatch HTML: %s", FEDWATCH_URL)
    html = fetch_html(FEDWATCH_URL)
    saved_path = save_html(html, OUTPUT_DIR)
    logger.info("Saved HTML snapshot: %s", saved_path)


if __name__ == "__main__":
    main()
