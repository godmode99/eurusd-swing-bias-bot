from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .auth import AuthState, visit_auth_and_detect, wait_for_login_form
from .config import DEFAULT_AUTH_URL
from .creds import pick_creds
from .debug import save_debug
from .watchlist import fetch_watchlist_html


@dataclass
class PipelineContext:
    page: object
    cfg: dict
    auth_url: str
    state: AuthState | None = None


@dataclass(frozen=True)
class PipelineStep:
    name: str
    action: Callable[[PipelineContext], bool]


def run_pipeline(ctx: PipelineContext, steps: Iterable[PipelineStep]) -> bool:
    for step in steps:
        print(f"➡️ {step.name}")
        if not step.action(ctx):
            print(f"⛔ pipeline stopped at: {step.name}")
            return False
    return True


def step_check_auth(ctx: PipelineContext) -> bool:
    try:
        ctx.state = visit_auth_and_detect(ctx.page, ctx.auth_url)
    except PlaywrightTimeoutError:
        print("❌ goto auth_url timeout")
        save_debug(ctx.page, "auth_timeout")
        return False
    print(f"STATE: {ctx.state} | url={ctx.page.url}")
    return True


def step_login(ctx: PipelineContext) -> bool:
    if ctx.state == AuthState.AUTHENTICATED:
        print("✅ Already logged in")
        return True

    print("⚠️ Need login -> จะพยายามกรอกให้")
    user, pwd = pick_creds(ctx.cfg)

    try:
        wait_for_login_form(ctx.page)
        ctx.page.fill("#user", user)
        ctx.page.fill("#pwd", pwd)
        ctx.page.click("#loginBtn")
        try:
            ctx.page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            pass
    except Exception as exc:
        print(f"❌ Error while filling login: {exc}")
    return True


def step_verify_login(ctx: PipelineContext) -> bool:
    try:
        ctx.state = visit_auth_and_detect(ctx.page, ctx.auth_url)
    except PlaywrightTimeoutError:
        print("❌ goto auth_url timeout")
        save_debug(ctx.page, "auth_timeout")
        return False
    print(f"AFTER LOGIN STATE: {ctx.state} | url={ctx.page.url}")

    if ctx.state == AuthState.AUTHENTICATED:
        print("✅ Login success")
    return True


def step_manual_recheck(ctx: PipelineContext) -> bool:
    if ctx.state == AuthState.AUTHENTICATED:
        return True

    print("❌ ยังไม่สำเร็จ (อาจติด reCAPTCHA/MFA/OTP หรือรหัสผิด)")
    print("➡️ ไปทำขั้นตอนบน browser ให้ผ่าน แล้วกลับมากด Enter เพื่อเช็คซ้ำ")
    input()

    try:
        ctx.state = visit_auth_and_detect(ctx.page, ctx.auth_url)
    except PlaywrightTimeoutError:
        print("❌ goto auth_url timeout")
        save_debug(ctx.page, "auth_timeout")
        return False
    print(f"AFTER MANUAL STATE: {ctx.state} | url={ctx.page.url}")

    if ctx.state == AuthState.AUTHENTICATED:
        print("✅ Success after manual")
        return True

    save_debug(ctx.page, "auth_failed")
    return False


def step_fetch_watchlist(ctx: PipelineContext) -> bool:
    if ctx.state != AuthState.AUTHENTICATED:
        return False
    fetch_watchlist_html(ctx.page, ctx.cfg)
    return True


def build_default_pipeline(page, cfg: dict) -> tuple[PipelineContext, list[PipelineStep]]:
    auth_url = (cfg.get("auth_url") or DEFAULT_AUTH_URL).strip()
    ctx = PipelineContext(page=page, cfg=cfg, auth_url=auth_url)
    steps = [
        PipelineStep("Check auth status", step_check_auth),
        PipelineStep("Login (auto)", step_login),
        PipelineStep("Verify login", step_verify_login),
        PipelineStep("Manual recheck", step_manual_recheck),
        PipelineStep("Fetch watchlist", step_fetch_watchlist),
    ]
    return ctx, steps
