"""
VARA Harvesters — Multi-plane RSS/HN signal acquisition (MCP vendor)
Operator: JRM-01 @liminaljermo
Expanded source list matching Real Vara operational coverage.
"""
from __future__ import annotations
import hashlib
import logging
import time
from typing import Optional, List
from dataclasses import dataclass

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
        ("https://www.wired.com/feed/rss", "wired", "main"),
        ("https://spectrum.ieee.org/rss/fulltext", "ieee_spectrum", "main"),
        ("https://venturebeat.com/category/ai/feed/", "venturebeat_ai", "main"),
        ("https://techcrunch.com/category/artificial-intelligence/feed/", "techcrunch_ai", "main"),
        ("https://www.theverge.com/ai-artificial-intelligence/rss/index.xml", "theverge_ai", "main"),
        ("https://news.mit.edu/rss/topic/artificial-intelligence", "mit_news_ai", "main"),
    ],
    "scientific": [
        ("https://arxiv.org/rss/cs.AI", "arxiv_ai", "main"),
        ("https://arxiv.org/rss/cs.LG", "arxiv_ml", "main"),
        ("https://arxiv.org/rss/cs.CL", "arxiv_nlp", "main"),
        ("https://arxiv.org/rss/cs.CR", "arxiv_sec", "main"),
        ("https://news.mit.edu/rss/topic/science", "mit_news_science", "main"),
        ("https://news.mit.edu/rss/topic/robotics", "mit_news_robotics", "main"),
    ],
    "adjacent_possible": [
        ("https://www.lesswrong.com/feed.xml", "lesswrong", "fringe"),
        ("https://forum.effectivealtruism.org/feed.xml", "ea_forum", "fringe"),
        ("https://scottaaronson.blog/?feed=rss2", "shtetl_optimized", "fringe"),
    ],
    "economic": [
        ("https://www.federalreserve.gov/feeds/press_all.xml", "federal_reserve", "main"),
        ("https://www.sec.gov/news/pressreleases.rss", "sec_press", "main"),
        ("https://feeds.bloomberg.com/markets/news.rss", "bloomberg_markets", "main"),
    ],
    "geopolitical": [
        ("https://feeds.bbci.co.uk/news/world/rss.xml", "bbc_world", "main"),
        ("https://www.aljazeera.com/xml/rss/all.xml", "aljazeera", "main"),
        ("https://rss.dw.com/xml/rss-en-all", "dw_world", "main"),
        ("https://foreignpolicy.com/feed/", "foreign_policy", "main"),
        ("https://www.bellingcat.com/feed/", "bellingcat", "fringe"),
    ],
    "social": [
        ("https://www.reddit.com/r/technology/.rss", "reddit_tech", "main"),
        ("https://www.reddit.com/r/MachineLearning/.rss", "reddit_ml", "main"),
        ("https://www.reddit.com/r/singularity/.rss", "reddit_sing", "fringe"),
    ],
    "dark": [
        ("https://www.bleepingcomputer.com/feed/", "bleepingcomputer", "main"),
        ("https://krebsonsecurity.com/feed/", "krebs_security", "main"),
        ("https://www.darkreading.com/rss.xml", "dark_reading", "main"),
        ("https://www.schneier.com/feed/atom", "schneier", "main"),
    ],
    "persons": [],
}


def _fetch_hn_top(n: int = 30) -> list:
    if not _NET:
        return []
    try:
        r = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10)
        r.raise_for_status()
        ids = r.json()[:n]
        stories = []
        for sid in ids:
            try:
                sr = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=5)
                sr.raise_for_status()
                item = sr.json()
                if item and item.get("title"):
                    stories.append(item)
                time.sleep(0.05)
            except Exception:
                continue
        return stories
    except Exception as e:
        logger.warning("HN fetch failed: %s", e)
        return []


def harvest_plane(plane: str, keywords: list, sweep_hours: int = 24, **kwargs) -> list:
    if not _NET:
        logger.warning("feedparser/requests not available — empty harvest for %s", plane)
        return []
    sources = list(RSS_SOURCES.get(plane, []))
    signals = []
    kw = keywords or ["AI", "agentic", "compute"]

    for feed_url, feed_id, tier in sources:
        try:
            feed = feedparser.parse(feed_url, request_headers={"User-Agent": "VaraHarvester/1.0"})
            for entry in feed.get("entries", [])[:25]:
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

    # HN enrichment for tech plane
    if plane == "tech":
        for item in _fetch_hn_top(25):
            title = item.get("title", "")
            url = item.get("url", f"https://news.ycombinator.com/item?id={item.get('id','')}")
            novelty = _keyword_density(title, kw)
            signals.append(HarvestedSignal(
                source_id=_compute_source_id(url, title),
                observation_id="obs:hn:" + str(item.get("id", "")),
                signal_id=_compute_signal_id("tech", title, title),
                plane="tech",
                content=title,
                title=title,
                url=url,
                raw_velocity=0.9,
                novelty_score=novelty,
                feed_tier="main",
            ))

    # Optional priority harvesters
    if plane in ("scientific", "tech"):
        try:
            from priority_harvesters import harvest_priority
            for s in harvest_priority(kw):
                if isinstance(s, dict) and s.get("plane") == plane:
                    signals.append(HarvestedSignal(**{k: s.get(k, getattr(HarvestedSignal, k, "") if False else s.get(k)) for k in
                        ["source_id","observation_id","signal_id","plane","content","title","url","raw_velocity","novelty_score","feed_tier"] if k in s})))
        except Exception:
            try:
                from priority_harvesters import harvest_priority
                extra = harvest_priority(kw)
                for s in extra:
                    if isinstance(s, dict):
                        signals.append(HarvestedSignal(
                            source_id=s.get("source_id", ""),
                            observation_id=s.get("observation_id", ""),
                            signal_id=s.get("signal_id", ""),
                            plane=s.get("plane", plane),
                            content=s.get("content", ""),
                            title=s.get("title", ""),
                            url=s.get("url", ""),
                            raw_velocity=float(s.get("raw_velocity", 0.7)),
                            novelty_score=float(s.get("novelty_score", 0.15)),
                            feed_tier=s.get("feed_tier", "main"),
                        ))
            except Exception as e:
                logger.debug("priority harvest skip: %s", e)

    return signals
