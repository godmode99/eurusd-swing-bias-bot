from __future__ import annotations

from enum import Enum

from .config import NAV_TIMEOUT


class AuthState(str, Enum):
    AUTHENTICATED = "AUTHENTICATED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    UNAUTHORIZED_OR_EXPIRED = "UNAUTHORIZED_OR_EXPIRED"
    UNKNOWN = "UNKNOWN"


def is_login_page(page) -> bool:
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

    try:
        page.wait_for_function(
            """() => {
                const u = document.querySelector('#user');
                const p = document.querySelector('#pwd');
                const b = document.querySelector('#loginBtn');
                const txt = document.body ? document.body.innerText.toLowerCase() : '';
                return (u && p && b) || txt.includes('session has expired') || txt.includes('unauthorized');
            }""",
            timeout=10_000,
        )
    except Exception:
        pass

    if is_login_page(page):
        return AuthState.LOGIN_REQUIRED

    body_txt = ""
    try:
        body_txt = page.locator("body").inner_text(timeout=2000).lower()
    except Exception:
        body_txt = ""

    if "session has expired" in body_txt or "unauthorized" in body_txt:
        return AuthState.UNAUTHORIZED_OR_EXPIRED

    return AuthState.UNKNOWN


def visit_auth_and_detect(page, auth_url: str) -> AuthState:
    response = page.goto(auth_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    page.wait_for_timeout(1200)
    response_text = None
    if response is not None:
        try:
            response_text = response.text()
        except Exception:
            response_text = None
    return detect_state(page, response_text=response_text)


def wait_for_login_form(page) -> None:
    page.wait_for_selector("#user", timeout=20_000)
    page.wait_for_selector("#pwd", timeout=20_000)
    page.wait_for_selector("#loginBtn", timeout=20_000)
