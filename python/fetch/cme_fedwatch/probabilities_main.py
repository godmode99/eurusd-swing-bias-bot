from __future__ import annotations

import logging
from datetime import datetime
import html
import re
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


def _extract_iframe_src(page_html: str) -> str | None:
    match = re.search(r'<iframe[^>]+src="([^"]+IntegratedFedWatchTool[^"]+)"', page_html)
    if not match:
        return None
    return html.unescape(match.group(1))


def fetch_iframe_html(page_html: str, referer: str) -> tuple[str | None, str | None]:
    iframe_src = _extract_iframe_src(page_html)
    if not iframe_src:
        return None, None
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
    }
    response = requests.get(iframe_src, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return iframe_src, response.text


def save_html(
    html: str,
    output_dir: Path,
    filename_prefix: str = "fedwatch_probabilities",
    latest_name: str | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    snapshot_path = output_dir / f"{filename_prefix}_{timestamp}.html"
    latest_filename = latest_name or f"latest_{filename_prefix}.html"
    latest_path = output_dir / latest_filename
    snapshot_path.write_text(html, encoding="utf-8")
    latest_path.write_text(html, encoding="utf-8")
    return snapshot_path


def main() -> None:
    logger = setup_logger()
    logger.info("Fetching CME FedWatch HTML: %s", FEDWATCH_URL)
    html = fetch_html(FEDWATCH_URL)
    saved_path = save_html(
        html,
        OUTPUT_DIR,
        filename_prefix="fedwatch_probabilities",
        latest_name="latest.html",
    )
    logger.info("Saved HTML snapshot: %s", saved_path)

    iframe_src, iframe_html = fetch_iframe_html(html, referer=FEDWATCH_URL)
    if iframe_html:
        iframe_path = save_html(
            iframe_html,
            OUTPUT_DIR,
            filename_prefix="fedwatch_probabilities_iframe",
            latest_name="latest_iframe.html",
        )
        logger.info("Saved iframe HTML snapshot: %s (%s)", iframe_path, iframe_src)
    else:
        logger.warning("FedWatch iframe not found; no data captured from embedded tool.")


if __name__ == "__main__":
    main()
