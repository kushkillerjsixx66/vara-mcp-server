"""
Firecrawl / Search Harvester for Vara
Operator: JRM-01 @liminaljermo

Optional plane for live web search when FIRECRAWL_API_KEY is set.
Falls back to empty list when key is missing (safe for serverless).
"""
from __future__ import annotations
import hashlib
import logging
import os
from typing import List, Optional

logger = logging.getLogger("vara.firecrawl")

try:
    import requests
    _NET = True
except ImportError:
    _NET = False


def _sid(url: str, title: str) -> str:
    return "src:" + hashlib.sha256(f"{url}:{title}".encode()).hexdigest()[:16]


def _sig(title: str, content: str) -> str:
    return "sig:" + hashlib.sha256(f"firecrawl:{title} {content}"[:2000].encode()).hexdigest()[:16]


def harvest_firecrawl(keywords: list, max_results: int = 15) -> list:
    """
    Query Firecrawl search if FIRECRAWL_API_KEY is present.
    Returns list of signal dicts on plane 'firecrawl' / 'tech'.
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not api_key or not _NET:
        logger.debug("Firecrawl skipped (no API key or no network libs)")
        return []

    query = " ".join(keywords[:8]) if keywords else "AI agents MCP"
    signals = []
    try:
        r = requests.post(
            "https://api.firecrawl.dev/v1/search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": query, "limit": max_results},
            timeout=20,
        )
        if r.status_code != 200:
            logger.warning("Firecrawl status %s", r.status_code)
            return []
        data = r.json()
        for item in data.get("data", [])[:max_results]:
            title = item.get("title", "")
            url = item.get("url", "")
            desc = (item.get("description") or item.get("markdown") or "")[:500]
            if not title and not url:
                continue
            signals.append({
                "source_id": _sid(url, title),
                "signal_id": _sig(title, desc),
                "observation_id": "obs:fc:" + hashlib.sha256(url.encode()).hexdigest()[:12],
                "plane": "tech",
                "title": title,
                "content": desc,
                "url": url,
                "raw_velocity": 0.8,
                "novelty_score": 0.2,
                "feed_tier": "main",
            })
    except Exception as e:
        logger.warning("Firecrawl harvest failed: %s", e)
    return signals


def harvest_plane_firecrawl(keywords: list, **kwargs) -> list:
    return harvest_firecrawl(keywords, max_results=kwargs.get("max_results", 15))
