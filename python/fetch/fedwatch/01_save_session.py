from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
DEFAULT_STATE_PATH = Path("secrets") / "fedwatch_storage.json"


def _resolve_state_path() -> Path:
    env_path = os.getenv("FEDWATCH_STORAGE_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_STATE_PATH


def main() -> int:
    state_path = _resolve_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)

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

        context.storage_state(path=str(state_path))
        browser.close()

    if not state_path.exists():
        print("Failed to create storage state.")
        return 1

    print(f"Saved session -> {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
