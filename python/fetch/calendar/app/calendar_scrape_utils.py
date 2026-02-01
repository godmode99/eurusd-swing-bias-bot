from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

URL_BASE = "https://www.forexfactory.com/calendar"
STATE_PATH = Path("ff_storage.json")

ART_DIR = Path("artifacts") / "ff"

MARKER = "window.calendarComponentStates[1] ="
STATE_RE = re.compile(r"(?:window\.)?calendarComponentStates\[\d+\]\s*=")
STATE_MAP_RE = re.compile(r"(?:window\.)?calendarComponentStates\s*=\s*\{")
STATE_ANY_RE = re.compile(r"calendarComponentStates\s*[:=]")
BKK = ZoneInfo("Asia/Bangkok")

IMPACT_SCORE = {"high": 3, "medium": 2, "low": 1}


@dataclass(frozen=True)
class FetchResult:
    day: date
    url: str
    html: str


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def bkk_now() -> datetime:
    return datetime.now(tz=BKK)


def bkk_today() -> date:
    return bkk_now().date()


def fmt_ff_day(day: date) -> str:
    month = day.strftime("%b").lower()
    return f"{month}{day.day}.{day.year}"


def build_day_url(day: date) -> str:
    return f"{URL_BASE}?day={fmt_ff_day(day)}"


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def extract_object_literal(html: str, marker: str) -> str:
    i = html.find(marker)
    if i == -1:
        raise RuntimeError("Marker not found: " + marker)

    obj_idx = html.find("{", i)
    arr_idx = html.find("[", i)
    if obj_idx == -1 and arr_idx == -1:
        raise RuntimeError("Object/array start not found after marker")

    if obj_idx == -1:
        j = arr_idx
    elif arr_idx == -1:
        j = obj_idx
    else:
        j = min(obj_idx, arr_idx)

    in_str = False
    esc = False
    quote = ""
    stack: list[str] = []
    pairs = {"{": "}", "[": "]"}
    closing = set(pairs.values())

    for k in range(j, len(html)):
        ch = html[k]

        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue

        if ch in ("'", '"'):
            in_str = True
            quote = ch
            continue

        if ch in pairs:
            stack.append(pairs[ch])
            continue
        if ch in closing:
            if stack:
                expected = stack.pop()
                if ch != expected:
                    raise RuntimeError("Unbalanced braces while extracting object")
                if not stack:
                    return html[j : k + 1]
            continue

    raise RuntimeError("Unbalanced braces while extracting object")


def quote_unquoted_keys(js: str) -> str:
    out: list[str] = []
    i = 0
    in_str = False
    esc = False
    quote = ""

    while i < len(js):
        ch = js[i]

        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            i += 1
            continue

        if ch in ('"', "'"):
            in_str = True
            quote = ch
            out.append(ch)
            i += 1
            continue

        if ch.isalpha() or ch == "_":
            j = len(out) - 1
            while j >= 0 and out[j].isspace():
                j -= 1
            prev = out[j] if j >= 0 else ""

            if prev in ("{", ","):
                start = i
                k = i + 1
                while k < len(js) and (js[k].isalnum() or js[k] == "_"):
                    k += 1
                ident = js[start:k]

                m = k
                while m < len(js) and js[m].isspace():
                    m += 1

                if m < len(js) and js[m] == ":":
                    out.append(f'"{ident}":')
                    i = m + 1
                    continue

        out.append(ch)
        i += 1

    return "".join(out)


def single_quotes_to_double(js: str) -> str:
    out: list[str] = []
    i = 0
    in_d = False
    in_s = False
    esc = False

    while i < len(js):
        ch = js[i]

        if in_d:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_d = False
            i += 1
            continue

        if in_s:
            if esc:
                out.append(ch)
                esc = False
                i += 1
                continue
            if ch == "\\":
                out.append(ch)
                esc = True
                i += 1
                continue
            if ch == "'":
                out.append('"')
                in_s = False
                i += 1
                continue
            if ch == '"':
                out.append('\\"')
            else:
                out.append(ch)
            i += 1
            continue

        if ch == '"':
            in_d = True
            out.append(ch)
            i += 1
            continue
        if ch == "'":
            in_s = True
            out.append('"')
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def strip_object_freeze(js: str) -> str:
    out: list[str] = []
    i = 0
    in_str = False
    esc = False
    quote = ""

    while i < len(js):
        ch = js[i]

        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            i += 1
            continue

        if ch in ('"', "'"):
            in_str = True
            quote = ch
            out.append(ch)
            i += 1
            continue

        if js.startswith("Object.freeze(", i):
            i += len("Object.freeze(")
            par = 1
            while i < len(js) and par > 0:
                c = js[i]

                if c in ('"', "'"):
                    q = c
                    out.append(c)
                    i += 1
                    esc2 = False
                    while i < len(js):
                        cc = js[i]
                        out.append(cc)
                        if esc2:
                            esc2 = False
                        elif cc == "\\":
                            esc2 = True
                        elif cc == q:
                            i += 1
                            break
                        i += 1
                    continue

                if c == "(":
                    par += 1
                    out.append(c)
                elif c == ")":
                    par -= 1
                    if par == 0:
                        i += 1
                        break
                    out.append(c)
                else:
                    out.append(c)

                i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def remove_trailing_commas(js: str) -> str:
    out: list[str] = []
    i = 0
    in_str = False
    esc = False
    quote = ""

    while i < len(js):
        ch = js[i]

        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            i += 1
            continue

        if ch in ('"', "'"):
            in_str = True
            quote = ch
            out.append(ch)
            i += 1
            continue

        if ch == ",":
            j = i + 1
            while j < len(js) and js[j].isspace():
                j += 1
            if j < len(js) and js[j] in ("}", "]"):
                i += 1
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def js_object_to_json_text(js_obj: str) -> str:
    s = quote_unquoted_keys(js_obj)
    s = single_quotes_to_double(s)
    s = strip_object_freeze(s)
    s = remove_trailing_commas(s)
    return s


def parse_epoch_to_bkk_iso(epoch: int | None) -> str:
    if not isinstance(epoch, int):
        return ""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(BKK).isoformat()


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    headers = list(rows[0].keys())

    def esc_csv(x: object) -> str:
        s = "" if x is None else str(x)
        if any(c in s for c in [",", '"', "\n"]):
            s = '"' + s.replace('"', '""') + '"'
        return s

    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(headers) + "\n")
        for r in rows:
            f.write(",".join(esc_csv(r.get(h)) for h in headers) + "\n")


def normalize_events(data: dict) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[int, int]] = set()

    for day in data.get("days", []):
        day_label = re.sub(r"<.*?>", "", day.get("date", "") or "")
        for ev in day.get("events", []):
            event_id = ev.get("id")
            epoch = ev.get("dateline")

            if not isinstance(event_id, int) or not isinstance(epoch, int):
                continue

            pk = (event_id, epoch)
            if pk in seen:
                continue
            seen.add(pk)

            impact = (ev.get("impactName") or "").lower().strip()
            impact_score = IMPACT_SCORE.get(impact, 0)

            rows.append(
                {
                    "day_label": day_label,
                    "event_id": event_id,
                    "dateline_epoch": epoch,
                    "datetime_bkk": parse_epoch_to_bkk_iso(epoch),
                    "currency": ev.get("currency"),
                    "country": ev.get("country"),
                    "impact": impact,
                    "impact_score": impact_score,
                    "timeLabel": ev.get("timeLabel"),
                    "name": ev.get("name"),
                    "prefixedName": ev.get("prefixedName"),
                    "actual": ev.get("actual"),
                    "forecast": ev.get("forecast"),
                    "previous": ev.get("previous"),
                    "revision": ev.get("revision"),
                    "url": ev.get("url"),
                    "soloUrl": ev.get("soloUrl"),
                }
            )

    rows.sort(key=lambda r: (r["dateline_epoch"], r["event_id"]))
    return rows


def find_calendar_state(data: object) -> dict | None:
    if isinstance(data, dict):
        if "days" in data:
            return data
        for value in data.values():
            if isinstance(value, dict) and "days" in value:
                return value
    if isinstance(data, list):
        for value in data:
            if isinstance(value, dict) and "days" in value:
                return value
    return None


def parse_calendar_state_literal(js_literal: str) -> dict:
    json_text = js_object_to_json_text(js_literal)
    data = json.loads(json_text)
    state = find_calendar_state(data)
    if state:
        return state
    raise RuntimeError("calendarComponentStates parsed but no days data found")


def extract_calendar_state(html: str) -> dict:
    match = STATE_RE.search(html)
    if match:
        literal = extract_object_literal(html, match.group(0))
        return parse_calendar_state_literal(literal)

    match = STATE_MAP_RE.search(html)
    if match:
        map_literal = extract_object_literal(html, match.group(0))
        return parse_calendar_state_literal(map_literal)

    match = STATE_ANY_RE.search(html)
    if match:
        literal = extract_object_literal(html, match.group(0))
        return parse_calendar_state_literal(literal)

    raise RuntimeError("Marker not found: calendarComponentStates")


def parse_calendar_html(html: str) -> list[dict]:
    data = extract_calendar_state(html)
    return normalize_events(data)


def fetch_calendar_htmls(days: Iterable[date], headless: bool = True) -> tuple[list[FetchResult], list[str]]:
    results: list[FetchResult] = []
    errors: list[str] = []

    if not STATE_PATH.exists():
        raise FileNotFoundError(
            f"Missing storage state file: {STATE_PATH.resolve()}\n"
            "Expected: ff_storage.json in repo root."
        )

    day_list = list(days)
    if not day_list:
        return results, errors

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            storage_state=str(STATE_PATH),
            viewport={"width": 1400, "height": 900},
            locale="en-US",
        )
        page = context.new_page()

        for day in day_list:
            url = build_day_url(day)
            html_text: Optional[str] = None

            def on_response(resp) -> None:
                nonlocal html_text
                try:
                    if resp.request.resource_type == "document" and resp.url.startswith(URL_BASE):
                        if resp.status == 200:
                            html_text = resp.text()
                except Exception:
                    pass

            page.on("response", on_response)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(3000)
                if not html_text:
                    html_text = page.content()
                if not html_text:
                    raise RuntimeError("No HTML captured")
                results.append(FetchResult(day=day, url=url, html=html_text))
            except Exception as exc:
                errors.append(f"{day.isoformat()} -> {url} :: {exc}")
            finally:
                page.remove_listener("response", on_response)

        context.close()
        browser.close()

    return results, errors


def output_paths(prefix: str) -> tuple[Path, Path]:
    ensure_dir(ART_DIR)
    ts = bkk_now().strftime("%Y%m%d_%H%M%S")
    json_path = ART_DIR / f"{prefix}_{ts}_bkk.json"
    csv_path = ART_DIR / f"{prefix}_{ts}_bkk.csv"
    return json_path, csv_path


def merge_events(base: list[dict], updates: list[dict]) -> tuple[list[dict], dict[str, int]]:
    def pk(e: dict) -> tuple[int, int] | None:
        try:
            return (int(e["event_id"]), int(e["dateline_epoch"]))
        except Exception:
            return None

    def is_blank(v: object) -> bool:
        if v is None:
            return True
        if isinstance(v, str) and v.strip() == "":
            return True
        return False

    base_map: dict[tuple[int, int], dict] = {}
    for e in base:
        key = pk(e)
        if key:
            base_map[key] = e

    matched = 0
    updated = 0
    updated_actual = 0

    refresh_fields = [
        "actual",
        "forecast",
        "previous",
        "revision",
        "impact",
        "impact_score",
        "timeLabel",
        "prefixedName",
        "name",
        "url",
        "soloUrl",
    ]

    for u in updates:
        key = pk(u)
        if not key or key not in base_map:
            continue
        matched += 1
        target = base_map[key]
        changed = False
        for field in refresh_fields:
            if field in u:
                uv = u.get(field)
                tv = target.get(field)
                if uv != tv and not (is_blank(uv) and is_blank(tv)):
                    target[field] = uv
                    changed = True
                    if field == "actual":
                        updated_actual += 1
        if changed:
            updated += 1

    base.sort(key=lambda r: (int(r.get("dateline_epoch", 0)), int(r.get("event_id", 0))))
    stats = {"matched": matched, "updated_any": updated, "updated_actual": updated_actual}
    return base, stats


def week_days(anchor: date) -> list[date]:
    start = anchor - timedelta(days=anchor.weekday())
    return [start + timedelta(days=i) for i in range(7)]
