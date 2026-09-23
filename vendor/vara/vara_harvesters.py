"""
VARA Harvesters — Minimal MCP vendor copy.
Attempts RSS/HN when feedparser/requests available; otherwise returns empty.
"""
from __future__ import annotations
import hashlib
import logging
from typing import Optional, List
from dataclasses import dataclass, field

logger = logging.getLogger("vara.harvesters")

try:
    import feedparser
    import requests
    _NET = True
except ImportError:
    _NET = False


@dataclass
class HarvestedSignal:
    source_id: str
    observation_id: str = ""
    signal_id: str = ""
    plane: str = "tech"
    content: str = ""
    title: str = ""
    url: str = ""
    raw_velocity: float = 0.5
    novelty_score: float = 0.1
    velocity_score: float = 0.0
    cluster_id: Optional[str] = None
    feed_tier: str = "main"


def _compute_source_id(url: str, title: str) -> str:
    return "src:" + hashlib.sha256(f"{url}:{title}".encode()).hexdigest()[:16]


def _compute_signal_id(plane: str, title: str, content: str) -> str:
    payload = f"{plane}:{title} {content}"[:2000]
    return "sig:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def _keyword_density(text: str, keywords: list) -> float:
    if not text or not keywords:
        return 0.0
    lower = text.lower()
    hits = sum(1 for kw in keywords if kw.lower() in lower)
    return round(min(1.0, hits / max(1, len(keywords) * 0.15)), 4)


RSS_SOURCES = {
    "tech": [
        ("https://news.ycombinator.com/rss", "hn_rss", "main"),
        ("https://www.technologyreview.com/feed/", "mit_tech_review", "main"),
    ],
    "scientific": [
        ("https://arxiv.org/rss/cs.AI", "arxiv_ai", "main"),
    ],
    "economic": [
        ("https://www.federalreserve.gov/feeds/press_all.xml", "federal_reserve", "main"),
    ],
    "geopolitical": [
        ("https://feeds.bbci.co.uk/news/world/rss.xml", "bbc_world", "main"),
    ],
}


def harvest_plane(plane: str, keywords: list, sweep_hours: int = 24, **kwargs) -> list:
    if not _NET:
        logger.warning("feedparser/requests not available — empty harvest for %s", plane)
        return []
    sources = RSS_SOURCES.get(plane, [])
    signals = []
    kw = keywords or ["AI", "agentic", "compute"]
    for feed_url, feed_id, tier in sources:
        try:
            feed = feedparser.parse(feed_url, request_headers={"User-Agent": "VaraHarvester/1.0"})
            for entry in feed.get("entries", [])[:20]:
                title = entry.get("title", "")
                content = entry.get("summary", "")[:500]
                url = entry.get("link", "")
                if not url:
                    continue
                novelty = _keyword_density(f"{title} {content}", kw)
                signals.append(HarvestedSignal(
                    source_id=_compute_source_id(url, title),
                    observation_id="obs:" + hashlib.sha256(f"{feed_id}:{url}".encode()).hexdigest()[:12],
                    signal_id=_compute_signal_id(plane, title, content),
                    plane=plane,
                    content=content,
                    title=title,
                    url=url,
                    raw_velocity=0.7,
                    novelty_score=novelty,
                    feed_tier=tier,
                ))
        except Exception as e:
            logger.warning("RSS fetch failed %s: %s", feed_url, e)
    return signals
