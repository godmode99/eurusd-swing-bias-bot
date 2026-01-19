from __future__ import annotations

import requests
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

FF_XML_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
FF_HEADERS = {
    "User-Agent": "eurusd-swing-bias-bot/1.0 (+https://nfs.faireconomy.media)",
    "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
}


def _safe_text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def normalize_impact(val: Any) -> str:
    s = str(val or "").strip()
    if not s:
        return ""
    sl = s.lower()
    if "high" in sl:
        return "High"
    if "med" in sl:
        return "Medium"
    if "low" in sl:
        return "Low"
    # sometimes FF uses other labels like "Holiday"
    return s


def normalize_currency(val: Any) -> str:
    return str(val or "").strip().upper()


def _looks_like_html(payload: str) -> bool:
    snippet = payload.lstrip()[:200].lower()
    return snippet.startswith("<!doctype html") or "<html" in snippet


def fetch_forexfactory_xml(timeout_seconds: int = 30) -> List[Dict[str, Any]]:
    r = requests.get(FF_XML_URL, headers=FF_HEADERS, timeout=timeout_seconds)
    r.raise_for_status()

    # FF XML often comes as windows-1252
    xml_text = r.content.decode("windows-1252", errors="replace")
    if _looks_like_html(xml_text):
        raise ValueError("ForexFactory XML returned HTML content (possible block).")
    root = ET.fromstring(xml_text)

    events: List[Dict[str, Any]] = []
    for ev in root.findall(".//event"):
        # tags commonly: title, country, currency, impact, date, time, forecast, previous, actual
        title = _safe_text(ev.find("title"))
        country = _safe_text(ev.find("country"))
        currency = normalize_currency(_safe_text(ev.find("currency")))
        impact = normalize_impact(_safe_text(ev.find("impact")))
        date_s = _safe_text(ev.find("date"))
        time_s = _safe_text(ev.find("time"))
        forecast = _safe_text(ev.find("forecast"))
        previous = _safe_text(ev.find("previous"))
        actual = _safe_text(ev.find("actual"))
        url = _safe_text(ev.find("url"))

        raw = {child.tag: _safe_text(child) for child in list(ev)}

        events.append(
            {
                "date": date_s,
                "time": time_s,
                "country": country,
                "currency": currency,
                "event": title,
                "impact": impact,
                "actual": actual,
                "forecast": forecast,
                "previous": previous,
                "url": url,
                "raw": raw,
            }
        )

    if not events:
        raise ValueError("ForexFactory XML returned no <event> nodes.")

    return events
