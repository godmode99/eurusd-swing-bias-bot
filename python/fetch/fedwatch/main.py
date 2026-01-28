from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from .config import load_config, resolve_user_data_dir
from .pipeline import build_default_pipeline, run_pipeline


def main() -> None:
    cfg = load_config()
    user_data_dir = resolve_user_data_dir(cfg)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
        )
        page = context.new_page()

        ctx, steps = build_default_pipeline(page, cfg)
        success = run_pipeline(ctx, steps)

        context.close()

        if not success:
            sys.exit(2)


if __name__ == "__main__":
    main()
