from __future__ import annotations

import json
import os
import sys
import getpass
from enum import Enum
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DEFAULT_AUTH_URL = "https://login.cmegroup.com/sso/accountstatus/showAuth.action"
NAV_TIMEOUT = 60_000

class AuthState(str, Enum):
    AUTHENTICATED = "AUTHENTICATED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    UNAUTHORIZED_OR_EXPIRED = "UNAUTHORIZED_OR_EXPIRED"
    UNKNOWN = "UNKNOWN"

def load_config() -> dict:
    cfg_path = Path(__file__).with_name("config.json")
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def pick_creds(cfg: dict):
    # 1) config.json
    user = (cfg.get("username") or "").strip()
    pwd  = (cfg.get("password") or "").strip()

    # 2) env fallback
    if not user:
        user = os.environ.get("CME_USER", "").strip()
    if not pwd:
        pwd = os.environ.get("CME_PASS", "").strip()

    # 3) prompt fallback
    if not user:
        user = input("CME username/email: ").strip()
    if not pwd:
        pwd = getpass.getpass("CME password: ").strip()

    return user, pwd

def is_login_page(page) -> bool:
    # จาก HTML ที่มึงแปะมา: #user, #pwd, #loginBtn
    return (
        page.locator("#user").count() > 0
        and page.locator("#pwd").count() > 0
        and page.locator("#loginBtn").count() > 0
    )

def detect_state(page, response_text: str | None = None) -> AuthState:
    text_upper = (response_text or "").upper()
    if "AUTHENTICATED" in text_upper:
        return AuthState.AUTHENTICATED
    if "LOGIN_REQUIRED" in text_upper:
        return AuthState.LOGIN_REQUIRED
    if "UNAUTHORIZED" in text_upper or "EXPIRED" in text_upper:
        return AuthState.UNAUTHORIZED_OR_EXPIRED

    # รอให้หน้า render นิดนึง กัน false positive
    try:
        page.wait_for_function(
            """() => {
                const u = document.querySelector('#user');
                const p = document.querySelector('#pwd');
                const b = document.querySelector('#loginBtn');
                const txt = document.body ? document.body.innerText.toLowerCase() : '';
                return (u && p && b) || txt.includes('session has expired') || txt.includes('unauthorized');
            }""",
            timeout=10_000
        )
    except:
        pass

    if is_login_page(page):
        return AuthState.LOGIN_REQUIRED

    # ถ้าไม่เจอ login form ก็ถือว่า authenticated สำหรับ showAuth URL
    body_txt = ""
    try:
        body_txt = page.locator("body").inner_text(timeout=2000).lower()
    except:
        body_txt = ""

    if "session has expired" in body_txt or "unauthorized" in body_txt:
        return AuthState.UNAUTHORIZED_OR_EXPIRED

    # ยังไงก็ไม่น่า UNKNOWN มาก แต่เผื่อไว้
    return AuthState.AUTHENTICATED

def save_debug(page, prefix="debug"):
    try:
        page.screenshot(path=f"{prefix}.png", full_page=True)
        print(f"📸 saved: {prefix}.png")
    except:
        pass
    try:
        html = page.content()
        with open(f"{prefix}.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"🧾 saved: {prefix}.html")
    except:
        pass

def main():
    cfg = load_config()

    auth_url = (cfg.get("auth_url") or DEFAULT_AUTH_URL).strip()
    user_data_dir = (cfg.get("user_data_dir") or os.environ.get("CME_USER_DATA_DIR") or "cme_profile").strip()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
        )
        page = context.new_page()

        # 1) เริ่มที่ auth_url เสมอ
        try:
            response = page.goto(auth_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            page.wait_for_timeout(1200)
        except PlaywrightTimeoutError:
            print("❌ goto auth_url timeout")
            save_debug(page, "auth_timeout")
            context.close()
            sys.exit(1)

        response_text = None
        if response is not None:
            try:
                response_text = response.text()
            except Exception:
                response_text = None
        state = detect_state(page, response_text=response_text)
        print(f"STATE: {state} | url={page.url}")

        if state == AuthState.AUTHENTICATED:
            print("✅ Already logged in")
            context.close()
            return

        # 2) ต้อง login
        print("⚠️ Need login -> จะพยายามกรอกให้")
        user, pwd = pick_creds(cfg)

        try:
            page.wait_for_selector("#user", timeout=20_000)
            page.wait_for_selector("#pwd", timeout=20_000)
            page.wait_for_selector("#loginBtn", timeout=20_000)

            page.fill("#user", user)
            page.fill("#pwd", pwd)
            page.click("#loginBtn")

            # อาจติด reCAPTCHA/MFA -> ให้ทำเองได้
            try:
                page.wait_for_load_state("networkidle", timeout=30_000)
            except:
                pass

        except Exception as e:
            print(f"❌ Error while filling login: {e}")

        # 3) เช็คซ้ำด้วย auth_url
        response = page.goto(auth_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        page.wait_for_timeout(1200)
        response_text = None
        if response is not None:
            try:
                response_text = response.text()
            except Exception:
                response_text = None
        state2 = detect_state(page, response_text=response_text)
        print(f"AFTER LOGIN STATE: {state2} | url={page.url}")

        if state2 == AuthState.AUTHENTICATED:
            print("✅ Login success")
            context.close()
            return

        print("❌ ยังไม่สำเร็จ (อาจติด reCAPTCHA/MFA/OTP หรือรหัสผิด)")
        print("➡️ ไปทำขั้นตอนบน browser ให้ผ่าน แล้วกลับมากด Enter เพื่อเช็คซ้ำ")
        input()

        response = page.goto(auth_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        page.wait_for_timeout(1200)
        response_text = None
        if response is not None:
            try:
                response_text = response.text()
            except Exception:
                response_text = None
        state3 = detect_state(page, response_text=response_text)
        print(f"AFTER MANUAL STATE: {state3} | url={page.url}")

        if state3 == AuthState.AUTHENTICATED:
            print("✅ Success after manual")
            context.close()
            return

        save_debug(page, "auth_failed")
        context.close()
        sys.exit(2)

if __name__ == "__main__":
    main()
