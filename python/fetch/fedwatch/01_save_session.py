from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
STATE_PATH = Path("secrets") / "fedwatch_storage.json"


def main() -> int:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="en-US",
        )
        page = context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=120000)

        print("\n- Please ensure the FedWatch page loads normally.")
        input("Press Enter to save session... ")

        context.storage_state(path=str(STATE_PATH))
        browser.close()

    if not STATE_PATH.exists():
        print("Failed to create storage state.")
        return 1

    print(f"Saved session -> {STATE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
