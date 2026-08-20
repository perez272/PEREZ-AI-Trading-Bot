"""Low-dependency news evidence layer.

News is advisory evidence only. Network errors, malformed feeds and stale
items never crash the trading loop and never create a positive signal.
Configure NEWS_RSS_URLS as a comma-separated list of trusted RSS/Atom feeds.
"""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_CACHE_SECONDS = 120
MAX_NEWS_AGE_SECONDS = 6 * 3600
DEFAULT_TIMEOUT_SECONDS = 6


@dataclass
class NewsItem:
    title: str
    summary: str
    url: str
    published_epoch: float


_CACHE: Dict[str, tuple[float, list[NewsItem]]] = {}


def _feeds() -> list[str]:
    raw = os.getenv("NEWS_RSS_URLS", "").strip()
    return [x.strip() for x in raw.split(",") if x.strip()][:8]


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _epoch(value: str) -> float:
    if not value:
        return 0.0
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _parse(xml_bytes: bytes) -> list[NewsItem]:
    root = ET.fromstring(xml_bytes)
    items: list[NewsItem] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in {"item", "entry"}:
            continue
        title = _text(next((x for x in node if x.tag.rsplit("}", 1)[-1] == "title"), None))
        summary = _text(next((x for x in node if x.tag.rsplit("}", 1)[-1] in {"description", "summary", "content"}), None))
        link_node = next((x for x in node if x.tag.rsplit("}", 1)[-1] == "link"), None)
        url = (link_node.attrib.get("href", "") if link_node is not None else "") or _text(link_node)
        date_node = next((x for x in node if x.tag.rsplit("}", 1)[-1] in {"pubDate", "published", "updated"}), None)
        published = _epoch(_text(date_node))
        if title:
            items.append(NewsItem(title[:300], summary[:1000], url[:1000], published))
    return items[:100]


def fetch_news() -> list[NewsItem]:
    """Fetch configured feeds with bounded timeout and in-process cache."""
    feeds = _feeds()
    if not feeds:
        return []
    now = time.time()
    output: list[NewsItem] = []
    for url in feeds:
        cached = _CACHE.get(url)
        if cached and now - cached[0] < DEFAULT_CACHE_SECONDS:
            output.extend(cached[1])
            continue
        try:
            request = Request(url, headers={"User-Agent": "PEREZ-AI-News/1.0"})
            with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
                data = response.read(1_500_000)
            parsed = _parse(data)
            _CACHE[url] = (now, parsed)
            output.extend(parsed)
        except Exception:
            # Keep stale cache as evidence only if it exists; never fabricate.
            if cached:
                output.extend(cached[1])
    return output


def score_symbol(symbol: str, items: Iterable[NewsItem] | None = None) -> Dict[str, Any]:
    """Return conservative keyword sentiment for a selected symbol."""
    symbol = str(symbol).upper().strip()
    items = list(items if items is not None else fetch_news())
    now = time.time()
    matched: list[NewsItem] = []
    positive = {"beat", "growth", "upgrade", "profit", "order", "contract", "approval", "buyback", "record", "strong", "surge"}
    negative = {"miss", "downgrade", "loss", "fraud", "probe", "penalty", "default", "cut", "weak", "fall", "ban", "warning"}
    score = 50.0
    for item in items:
        if item.published_epoch and now - item.published_epoch > MAX_NEWS_AGE_SECONDS:
            continue
        text = f"{item.title} {item.summary}".upper()
        if symbol not in text:
            continue
        matched.append(item)
        words = set(re.findall(r"[A-Z][A-Z0-9-]{2,}", text.lower()))
        pos = len(words & positive)
        neg = len(words & negative)
        score += (pos - neg) * 6.0
    score = max(0.0, min(100.0, score))
    return {
        "available": bool(matched),
        "score": round(score, 2) if matched else 50.0,
        "count": len(matched),
        "items": [
            {"title": x.title, "url": x.url, "published_epoch": x.published_epoch}
            for x in matched[:5]
        ],
    }


def search_symbol_news(symbol: str) -> Dict[str, Any]:
    """Convenience wrapper used by the live updater/scanner."""
    return score_symbol(symbol)
