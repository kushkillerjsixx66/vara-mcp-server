"""
Differential / ETag Harvest for Vara
Operator: JRM-01 @liminaljermo

Watches pages for content changes via ETag / hash.
Emits signals when watched URLs change.
"""

from __future__ import annotations
import hashlib
import json
import os
import logging
from typing import List, Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger("vara.differential")

STATE_PATH = "differential_state.json"

# Default watched pages (lab blogs, system cards, protocol hubs)
DEFAULT_WATCH_URLS = [
    ("https://openai.com/blog/rss.xml", "openai_blog", "tech"),
    ("https://www.anthropic.com/news", "anthropic_news", "tech"),
    ("https://deepmind.google/discover/blog/", "deepmind_blog", "tech"),
    ("https://ai.meta.com/blog/", "meta_ai_blog", "tech"),
]


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def _hash_content(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:24]


def check_url_change(url: str, feed_id: str, plane: str = "tech", state: Optional[dict] = None) -> Optional[dict]:
    """
    Fetch URL and compare content hash to last seen.
    Returns a signal dict if changed, else None.
    """
    if state is None:
        state = load_state()
    try:
        import requests
        r = requests.get(url, timeout=12, headers={"User-Agent": "VaraDifferential/1.0"})
        r.raise_for_status()
        body = r.text[:50000]
        etag = r.headers.get("ETag", "")
        h = _hash_content(body)
        prev = state.get(feed_id, {})
        if prev.get("hash") == h and (not etag or prev.get("etag") == etag):
            return None  # no change
        state[feed_id] = {"hash": h, "etag": etag, "url": url}
        save_state(state)
        title = f"Change detected: {feed_id}"
        return {
            "source_id": f"diff:{feed_id}",
            "signal_id": f"sig:diff:{feed_id}:{h[:8]}",
            "observation_id": f"obs:diff:{h[:12]}",
            "plane": plane,
            "title": title,
            "content": body[:400],
            "url": url,
            "raw_velocity": 0.85,
            "novelty_score": 0.22,
            "feed_tier": "main",
            "differential": True,
        }
    except Exception as e:
        logger.warning("differential check failed %s: %s", url, e)
        return None


def harvest_differential(watch_urls: Optional[list] = None, **kwargs) -> list:
    """Run differential checks on all watched URLs. Returns list of change signals."""
    urls = watch_urls or DEFAULT_WATCH_URLS
    state = load_state()
    signals = []
    for item in urls:
        if len(item) == 3:
            url, feed_id, plane = item
        else:
            url, feed_id = item[0], item[1]
            plane = "tech"
        sig = check_url_change(url, feed_id, plane, state)
        if sig:
            signals.append(sig)
    return signals
