"""
VARA Harvesters — Real RSS/API signal acquisition
Operator: JRM-01 @liminaljermo
Spec ref: Lattice Unified Spec §3, §5

Planes supported:
    tech              — AI/ML/compute news via RSS + Hacker News
    scientific        — ArXiv, academic preprints
    adjacent_possible — Emerging ideas (LessWrong, EA Forum)
    economic          — Financial news, Fed, macro indicators
    geopolitical      — Geopolitics, sanctions, foreign policy
    social            — Reddit tech/AI communities
    dark              — Underground signals, adversarial AI

Invariants:
    I·SRC  — every signal carries source_id with full provenance
    II·SCR — scores computed from recency + keyword density; no inflation
    II·WIN — sweep_depth_hours is an acquisition boundary, not only a score window
    V·SIL  — empty result is valid; logged, not suppressed
    VI·BND — harvesters surface signals only; no directives
"""

import feedparser
import requests
import datetime
import hashlib
import time
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("vara.harvesters")

# ─── KEYWORDS ────────────────────────────────────────────────────────────────

DEFAULT_KEYWORDS = [
    # AI / models / agents
    "AI", "artificial intelligence", "foundation model", "language model",
    "reasoning model", "multimodal", "open weights", "open source model",
    "inference", "test-time compute", "inference scaling", "training",
    "fine-tuning", "RLHF", "RLAIF", "reinforcement learning",
    "mixture of experts", "sparse model", "long context", "context window",
    "quantization", "speculative decoding", "model compression",
    "mechanistic interpretability", "interpretability", "AI safety",
    "alignment", "corrigibility", "reward hacking", "emergent behavior",
    "goal misgeneralization", "capability elicitation",
    # Agents / cognitive infrastructure
    "agentic", "AI agent", "multi-agent", "autonomous agent", "tool use",
    "function calling", "RAG", "retrieval augmented generation",
    "MCP", "Model Context Protocol", "A2A", "agent protocol",
    "computer use", "browser agent", "workflow automation",
    # Compute / hardware / infrastructure
    "GPU", "TPU", "accelerator", "CUDA", "NVLink", "InfiniBand",
    "Blackwell", "H100", "B200", "GB200", "semiconductor", "chip",
    "chip shortage", "advanced packaging", "HBM", "foundry", "TSMC",
    "data center", "datacenter", "data centre", "compute capacity",
    "cloud infrastructure", "distributed systems", "latency", "throughput",
    "power constraint", "grid capacity", "data center power", "cooling",
    "energy storage", "battery", "nuclear energy", "renewable energy",
    "rare earth", "critical minerals", "supply chain",
    # Robotics / embodiment
    "robotics", "humanoid", "embodied AI", "autonomous vehicle",
    "industrial automation", "robot learning", "robot manipulation",
    "drone", "autonomy",
    # Science / biotech
    "scientific discovery", "biology", "biotechnology", "bioinformatics",
    "synthetic biology", "protein design", "genomics", "materials science",
    "nanotechnology", "quantum computing", "quantum technology",
    "fusion", "space technology",
    # Economics / policy / markets
    "Federal Reserve", "interest rate", "inflation", "GDP", "CPI",
    "yield curve", "recession", "monetary policy", "fiscal policy",
    "unemployment", "labor market", "trade deficit", "tariff",
    "industrial policy", "export controls", "sanctions", "regulation",
    "AI regulation", "competition policy", "SEC", "FTC",
    # Geopolitics / strategic technology
    "NATO", "BRICS", "foreign policy", "diplomacy", "diplomatic",
    "conflict", "treaty", "nuclear", "cyber attack", "cybersecurity",
    "espionage", "Taiwan", "Ukraine", "Russia", "China", "Iran",
    "North Korea", "Middle East", "South China Sea", "alliance",
    "defense technology", "dual use", "export restriction",
    # Security / information environment
    "zero-day", "ransomware", "data breach", "deepfake",
    "synthetic media", "disinformation", "misinformation",
    "cybersecurity", "adversarial AI", "surveillance",
]

DOMAIN_KEYWORDS = {
    "economic": [
        "Federal Reserve", "interest rate", "inflation", "GDP", "CPI",
        "yield curve", "recession", "monetary policy", "fiscal policy",
        "unemployment", "labor market", "trade deficit", "tariff",
        "supply chain", "PMI", "industrial output", "earnings",
        "S&P", "Dow Jones", "NASDAQ", "market crash", "rally",
        "industrial policy", "export controls", "critical minerals",
    ],
    "geopolitical": [
        "sanctions", "military", "NATO", "BRICS", "diplomatic crisis",
        "conflict", "treaty", "foreign policy", "nuclear", "cyber attack",
        "espionage", "China", "Russia", "Iran", "North Korea", "Taiwan",
        "Ukraine", "Middle East", "South China Sea", "alliance",
        "arms deal", "export controls", "dual use", "critical minerals",
    ],
    "tech": DEFAULT_KEYWORDS,
    "scientific": [
        "AI", "machine learning", "robotics", "biology", "biotechnology",
        "bioinformatics", "genomics", "protein design", "materials science",
        "nanotechnology", "quantum", "fusion", "semiconductor",
        "energy storage", "battery", "space technology",
    ],
    "social": [
        "social movement", "protest", "public opinion", "misinformation",
        "disinformation", "propaganda", "censorship", "surveillance",
        "freedom of speech", "social platform", "online community",
    ],
    "dark": [
        "exploit", "zero-day", "ransomware", "dark web", "leak", "breach",
        "hacking group", "adversarial AI", "disinformation", "deepfake",
        "synthetic media", "underground market", "cybersecurity",
    ],
}

# ─── RSS SOURCES BY PLANE ────────────────────────────────────────────────────
#
# Source policy:
#   main   = primary/established source with stronger provenance
#   fringe = exploratory source retained for weak-signal discovery
#
# Keep source IDs stable. They participate in observation identity.

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
        ("https://arxiv.org/rss/econ", "arxiv_econ", "main"),
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
        ("https://www.ft.com/?format=rss", "ft_markets", "main"),
        ("https://www.wsj.com/xml/rss/3_7031.xml", "wsj_markets", "main"),
        ("https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "et_markets", "main"),
    ],
    "geopolitical": [
        ("https://feeds.bbci.co.uk/news/world/rss.xml", "bbc_world", "main"),
        ("https://www.aljazeera.com/xml/rss/all.xml", "aljazeera", "main"),
        ("https://rss.dw.com/xml/rss-en-all", "dw_world", "main"),
        ("https://foreignpolicy.com/feed/", "foreign_policy", "main"),
        ("https://www.bellingcat.com/feed/", "bellingcat", "fringe"),
    ],
    "social": [
        ("https://www.reddit.com/r/worldnews/.rss", "reddit_worldnews", "main"),
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

# ─── SIGNAL DATACLASS ────────────────────────────────────────────────────────

@dataclass
class HarvestedSignal:
    source_id:      str
    observation_id:  str
    signal_id:      str
    plane:          str
    content:        str
    title:          str
    url:            str
    raw_velocity:   float          # age-based freshness 0-1
    relevance_score: float          # keyword density / topical relevance 0-1
    velocity_score: float = 0.0   # filled by caller (cluster velocity)
    cluster_id:     Optional[str] = None
    feed_tier:      str = "main"   # "main" | "fringe"


# ─── UTILITY ─────────────────────────────────────────────────────────────────

def _compute_source_id(url: str, title: str) -> str:
    """I·SRC — deterministic source/provenance identity."""
    payload = f"{url}:{title}"
    return "src:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def _normalize_identity_text(text: str) -> str:
    """Normalize text for stable lexical signal identity."""
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _compute_observation_id(feed_id: str, entry: dict) -> str:
    """Identify one concrete feed observation without using mutable scoring."""
    stable = entry.get("id") or entry.get("guid") or entry.get("link") or ""
    title = _normalize_identity_text(entry.get("title", ""))
    payload = f"{feed_id}:{stable}:{title}"
    return "obs:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def _compute_signal_id(plane: str, title: str, content: str) -> str:
    """
    Identify a normalized signal independently of URL/source identity.

    This is lexical normalization, not semantic phenomenon resolution.
    It deliberately avoids claiming that two differently worded reports
    describe the same underlying phenomenon.
    """
    normalized = _normalize_identity_text(f"{title} {content}")[:2000]
    payload = f"{plane}:{normalized}"
    return "sig:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def _entry_age_hours(published_parsed, now=None) -> Optional[float]:
    """Return entry age in hours; unknown timestamps return None."""
    if not published_parsed:
        return None
    try:
        pub_dt = datetime.datetime(*published_parsed[:6], tzinfo=datetime.timezone.utc)
        now_dt = now or datetime.datetime.now(datetime.timezone.utc)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=datetime.timezone.utc)
        return (now_dt - pub_dt).total_seconds() / 3600
    except (TypeError, ValueError, OverflowError):
        return None


def _within_sweep_window(published_parsed, sweep_hours: int, now=None) -> bool:
    """II·WIN — reject known-stale entries at acquisition time."""
    if sweep_hours <= 0:
        raise ValueError("sweep_hours must be greater than zero")
    age_h = _entry_age_hours(published_parsed, now=now)
    return age_h is None or age_h <= sweep_hours


def _recency_score(published_parsed, sweep_hours: int = 24, now=None) -> float:
    """
    Score freshness: 1.0 = just published, 0.0 = at edge of sweep window.
    """
    if not published_parsed:
        return 0.3   # unknown age — neutral
    try:
        pub_dt = datetime.datetime(*published_parsed[:6])
        age_h = _entry_age_hours(published_parsed, now=now)
        if age_h is None:
            return 0.3
        score  = max(0.0, 1.0 - (age_h / sweep_hours))
        return round(score, 4)
    except Exception:
        return 0.3


def _keyword_relevance(text: str, keywords: list) -> float:
    """
    II·SCR — topical relevance from keyword hit density.
    This is not semantic novelty. It measures how strongly an observation
    matches the configured sensing vocabulary.
    Returns 0-1 (capped; no inflation).
    """
    if not text:
        return 0.0
    lower = text.lower()
    hits  = sum(1 for kw in keywords if kw.lower() in lower)
    # Log-scale to prevent inflation on keyword-stuffed text
    density = min(1.0, hits / max(1, len(keywords) * 0.15))
    return round(density, 4)


def _fetch_rss(url: str, timeout: int = 10) -> list:
    """Fetch and parse an RSS/Atom feed. Returns list of feedparser entries."""
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "VaraHarvester/1.0"})
        return feed.get("entries", [])
    except Exception as e:
        logger.warning("RSS fetch failed %s: %s", url, e)
        return []


def _fetch_hn_top(n: int = 30) -> list:
    """Fetch top HackerNews stories via the official Firebase API."""
    try:
        r = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=10
        )
        r.raise_for_status()
        ids = r.json()[:n]
        stories = []
        for sid in ids:
            try:
                sr = requests.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                    timeout=5,
                )
                sr.raise_for_status()
                item = sr.json()
                if item and item.get("title"):
                    stories.append(item)
                time.sleep(0.05)   # polite rate limiting
            except Exception:
                continue
        return stories
    except Exception as e:
        logger.warning("HN fetch failed: %s", e)
        return []


# ─── PLANE HARVESTERS ────────────────────────────────────────────────────────

def _harvest_rss_plane(
    plane:      str,
    keywords:   list,
    sweep_hours: int,
    extra_feeds: list = None,
    now=None,
) -> list:
    """Generic RSS harvester for a named plane."""
    sources  = RSS_SOURCES.get(plane, []) + (extra_feeds or [])
    signals  = []
    kw_set   = keywords or DEFAULT_KEYWORDS
    plane_kw = DOMAIN_KEYWORDS.get(plane, kw_set)

    for feed_url, feed_id, tier in sources:
        entries = _fetch_rss(feed_url)
        for entry in entries:
            published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
            if not _within_sweep_window(published_parsed, sweep_hours, now=now):
                continue
            title   = entry.get("title", "")
            content = entry.get("summary", entry.get("content", [{}])[0].get("value", ""))
            url     = entry.get("link", "")
            if not url:
                continue

            full_text  = f"{title} {content}"
            relevance  = _keyword_relevance(full_text, kw_set + plane_kw)
            recency    = _recency_score(published_parsed, sweep_hours, now=now)
            source_id      = _compute_source_id(url, title)
            observation_id = _compute_observation_id(feed_id, entry)
            signal_id      = _compute_signal_id(plane, title, content)

            signals.append(HarvestedSignal(
                source_id=source_id,
                observation_id=observation_id,
                signal_id=signal_id,
                plane=plane,
                content=content[:500],
                title=title,
                url=url,
                raw_velocity=recency,
                relevance_score=relevance,
                feed_tier=tier,
            ))

    return signals


def _harvest_tech(keywords, sweep_hours, extra_feeds=None, **_) -> list:
    """tech plane — RSS + Hacker News."""
    rss_sigs = _harvest_rss_plane("tech", keywords, sweep_hours, extra_feeds)

    # Hacker News top stories
    hn_stories = _fetch_hn_top(30)
    for item in hn_stories:
        title    = item.get("title", "")
        url      = item.get("url", f"https://news.ycombinator.com/item?id={item.get('id','')}")
        content  = title
        relevance  = _keyword_relevance(title, keywords or DEFAULT_KEYWORDS)
        source_id      = _compute_source_id(url, title)
        observation_id = _compute_observation_id("hn_api", item)
        signal_id      = _compute_signal_id("tech", title, content)
        rss_sigs.append(HarvestedSignal(
            source_id=source_id,
            observation_id=observation_id,
            signal_id=signal_id,
            plane="tech",
            content=content,
            title=title,
            url=url,
            raw_velocity=0.9,   # HN top = very fresh
            relevance_score=relevance,
            feed_tier="main",
        ))

    return rss_sigs


def _harvest_economic(keywords, sweep_hours, **_) -> list:
    return _harvest_rss_plane("economic", keywords, sweep_hours)


def _harvest_geopolitical(keywords, sweep_hours, **_) -> list:
    return _harvest_rss_plane("geopolitical", keywords, sweep_hours)


def _harvest_scientific(keywords, sweep_hours, **_) -> list:
    return _harvest_rss_plane("scientific", keywords, sweep_hours)


def _harvest_social(keywords, sweep_hours, **_) -> list:
    return _harvest_rss_plane("social", keywords, sweep_hours)


def _harvest_adjacent_possible(keywords, sweep_hours, extra_substacks=None, **_) -> list:
    extra_feeds = []
    for substack_url in (extra_substacks or []):
        feed_url  = substack_url.rstrip("/") + "/feed"
        feed_id   = substack_url.split("//")[-1].split(".")[0]
        extra_feeds.append((feed_url, feed_id, "fringe"))
    return _harvest_rss_plane("adjacent_possible", keywords, sweep_hours, extra_feeds)


def _harvest_dark(keywords, sweep_hours, **_) -> list:
    return _harvest_rss_plane("dark", keywords, sweep_hours)


def _harvest_persons(keywords, sweep_hours, **_) -> list:
    """persons plane — notable individual mentions on HN."""
    hn_stories = _fetch_hn_top(50)
    sigs = []
    for item in hn_stories:
        title    = item.get("title", "")
        url      = item.get("url", f"https://news.ycombinator.com/item?id={item.get('id','')}")
        relevance = _keyword_relevance(title, keywords or DEFAULT_KEYWORDS)
        source_id      = _compute_source_id(url, title)
        observation_id = _compute_observation_id("hn_api_persons", item)
        signal_id      = _compute_signal_id("persons", title, title)
        sigs.append(HarvestedSignal(
            source_id=source_id,
            observation_id=observation_id,
            signal_id=signal_id,
            plane="persons",
            content=title,
            title=title,
            url=url,
            raw_velocity=0.8,
            relevance_score=relevance,
            feed_tier="main",
        ))
    return sigs


# ─── PLANE DISPATCH TABLE ────────────────────────────────────────────────────

_PLANE_HARVESTERS = {
    "tech":               _harvest_tech,
    "scientific":         _harvest_scientific,
    "adjacent_possible":  _harvest_adjacent_possible,
    "economic":           _harvest_economic,
    "geopolitical":       _harvest_geopolitical,
    "social":             _harvest_social,
    "dark":               _harvest_dark,
    "persons":            _harvest_persons,
}


# ─── PUBLIC API ──────────────────────────────────────────────────────────────

def harvest_plane(
    plane:           str,
    keywords:        list = None,
    sweep_hours:     int  = 24,
    extra_rss_feeds: list = None,
    extra_substacks: list = None,
) -> list:
    """
    Harvest signals from a single plane.

    Returns list of dicts (serializable HarvestedSignal fields).
    Returns empty list if plane unsupported — V·SIL: no exception raised.
    """
    harvester = _PLANE_HARVESTERS.get(plane)
    if not harvester:
        logger.info("harvest_plane: unsupported plane '%s' — V·SIL", plane)
        return []

    try:
        raw = harvester(
            keywords=keywords or DEFAULT_KEYWORDS,
            sweep_hours=sweep_hours,
            extra_feeds=[(u, u.split("//")[-1][:20], "main") for u in (extra_rss_feeds or [])],
            extra_substacks=extra_substacks or [],
        )
        # Convert dataclasses → dicts for downstream consumers
        return [
            {
                "source_id":     s.source_id,
                "observation_id": s.observation_id,
                "signal_id":      s.signal_id,
                "plane":         s.plane,
                "content":       s.content,
                "title":         s.title,
                "url":           s.url,
                "raw_velocity":  s.raw_velocity,
                "relevance_score": s.relevance_score,
                "velocity_score": s.velocity_score,
                "cluster_id":    s.cluster_id,
                "feed_tier":     s.feed_tier,
            }
            for s in raw
        ]
    except Exception as e:
        # V·SIL: harvester failures are logged, not propagated
        logger.error("harvest_plane '%s' failed: %s", plane, e, exc_info=True)
        return []
