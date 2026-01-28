from __future__ import annotations

import getpass
import os


def pick_creds(cfg: dict) -> tuple[str, str]:
    user = (cfg.get("username") or "").strip()
    pwd = (cfg.get("password") or "").strip()

    if not user:
        user = os.environ.get("CME_USER", "").strip()
    if not pwd:
        pwd = os.environ.get("CME_PASS", "").strip()

    if not user:
        user = input("CME username/email: ").strip()
    if not pwd:
        pwd = getpass.getpass("CME password: ").strip()

    return user, pwd
