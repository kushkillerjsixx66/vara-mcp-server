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
    V·SIL  — empty result is valid; logged, not suppressed
    VI·BND — harvesters surface signals only; no directives
"""

import feedparser
import requests
import datetime
import hashlib
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("vara.harvesters")

# ─── KEYWORDS ────────────────────────────────────────────────────────────────

DEFAULT_KEYWORDS = [
    # ── Original ─────────────────────────────────────────────────
    "AI", "artificial intelligence", "frameworks", "bottlenecks",
    "compute", "infrastructure", "error remediation", "GPU", "LLM",
    "model training", "inference", "latency", "throughput", "CUDA",
    "distributed systems", "data center", "chip shortage", "scaling",
    # ── Models & Architecture ─────────────────────────────────────
    "reasoning model", "inference scaling", "test-time compute",
    "mixture of experts", "MoE", "sparse model", "context window",
    "long context", "RLHF", "RLAIF", "constitutional AI",
    "speculative decoding", "quantization", "LoRA", "fine-tuning",
    "agentic", "multi-agent", "tool use", "function calling", "RAG",
    # ── Releases & Benchmarks ─────────────────────────────────────
    "new model", "just released", "open weights", "open source",
    "state of the art", "SOTA", "beats GPT", "outperforms",
    "benchmark", "announced today", "breaking",
    # ── Safety & Alignment ────────────────────────────────────────
    "alignment", "mesa-optimizer", "deceptive alignment",
    "corrigibility", "reward hacking", "emergent behavior",
    "interpretability", "mechanistic interpretability",
    "superposition", "AI safety", "x-risk", "existential risk",
    "capability elicitation", "goal misgeneralization",
    # ── Hardware & Infrastructure ─────────────────────────────────
    "H100", "B200", "Blackwell", "GB200", "NVLink", "InfiniBand",
    "TPU", "datacenter capacity", "power constraint",
    # ── Economics ─────────────────────────────────────────────────
    "Federal Reserve", "interest rate", "inflation", "GDP", "CPI",
    "yield curve", "recession", "monetary policy", "fiscal",
    "unemployment", "labor market", "trade deficit", "tariff",
    # ── Geopolitics ───────────────────────────────────────────────
    "sanctions", "military", "NATO", "BRICS", "diplomatic",
    "conflict", "treaty", "foreign policy", "coup", "proxy war",
    "nuclear", "cyber attack", "espionage",
    # ── Crypto / Finance ──────────────────────────────────────────
    "Bitcoin", "BTC", "ETH", "crypto", "blockchain", "DeFi",
    "stablecoin", "regulation", "SEC", "exchange",
]

DOMAIN_KEYWORDS = {
    "economic": [
        "Federal Reserve", "interest rate", "inflation", "GDP", "CPI",
        "yield curve", "recession", "monetary policy", "fiscal policy",
        "unemployment", "labor market", "trade deficit", "tariff",
        "supply chain", "PMI", "industrial output", "earnings",
        "S&P", "Dow Jones", "NASDAQ", "market crash", "rally",
    ],
    "geopolitical": [
        "sanctions", "military", "NATO", "BRICS", "diplomatic crisis",
        "conflict", "treaty", "foreign policy", "coup", "proxy war",
        "nuclear", "cyber attack", "espionage", "USA", "China", "Russia",
        "Iran", "North Korea", "Taiwan", "Ukraine", "Middle East",
        "South China Sea", "alliance", "arms deal",
    ],
    "tech": DEFAULT_KEYWORDS,
    "social": [
        "protest", "social movement", "election", "democracy", "human rights",
        "civil unrest", "public opinion", "misinformation", "propaganda",
        "censorship", "freedom of speech", "surveillance",
    ],
    "dark": [
        "exploit", "zero-day", "ransomware", "dark web", "leak",
        "breach", "hacking group", "adversarial AI", "disinformation",
        "deepfake", "synthetic media", "underground market",
    ],
}

# ─── RSS SOURCES BY PLANE ────────────────────────────────────────────────────

RSS_SOURCES = {
    "tech": [
        ("https://feeds.feedburner.com/oreilly/radar",            "oreilly_radar",    "main"),
        ("https://news.ycombinator.com/rss",                      "hn_rss",           "main"),
        ("https://www.technologyreview.com/feed/",                "mit_tech_review",  "main"),
        ("https://www.wired.com/feed/rss",                        "wired",            "main"),
        ("https://spectrum.ieee.org/rss/fulltext",                "ieee_spectrum",    "main"),
        ("https://venturebeat.com/category/ai/feed/",             "venturebeat_ai",   "main"),
        ("https://techcrunch.com/category/artificial-intelligence/feed/", "techcrunch_ai", "main"),
        ("https://www.theverge.com/ai-artificial-intelligence/rss/index.xml", "theverge_ai", "main"),
    ],
    "scientific": [
        ("https://arxiv.org/rss/cs.AI",  "arxiv_ai",  "main"),
        ("https://arxiv.org/rss/cs.LG",  "arxiv_ml",  "main"),
        ("https://arxiv.org/rss/cs.CL",  "arxiv_nlp", "main"),
        ("https://arxiv.org/rss/cs.CR",  "arxiv_sec", "main"),
        ("https://arxiv.org/rss/econ",   "arxiv_econ","main"),
    ],
    "adjacent_possible": [
        ("https://www.lesswrong.com/feed.xml",   "lesswrong",    "fringe"),
        ("https://forum.effectivealtruism.org/feed.xml", "ea_forum", "fringe"),
        ("https://scottaaronson.blog/?feed=rss2", "shtetl_optimized", "fringe"),
    ],
    "economic": [
        ("https://feeds.feedburner.com/reuters/businessNews", "reuters_business", "main"),
        ("https://feeds.bloomberg.com/markets/news.rss",      "bloomberg_markets", "main"),
        ("https://www.ft.com/?format=rss",                    "ft_markets",       "main"),
        ("https://www.wsj.com/xml/rss/3_7031.xml",            "wsj_markets",      "main"),
        ("https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "et_markets", "main"),
    ],
    "geopolitical": [
        ("https://feeds.bbci.co.uk/news/world/rss.xml",        "bbc_world",        "main"),
        ("https://www.aljazeera.com/xml/rss/all.xml",          "aljazeera",        "main"),
        ("https://feeds.feedburner.com/reuters/worldnews",     "reuters_world",    "main"),
        ("https://rss.dw.com/xml/rss-en-all",                  "dw_world",         "main"),
        ("https://foreignpolicy.com/feed/",                    "foreign_policy",   "main"),
        ("https://www.bellingcat.com/feed/",                   "bellingcat",       "fringe"),
    ],
    "social": [
        ("https://www.reddit.com/r/worldnews/.rss",            "reddit_worldnews", "main"),
        ("https://www.reddit.com/r/technology/.rss",           "reddit_tech",      "main"),
        ("https://www.reddit.com/r/MachineLearning/.rss",      "reddit_ml",        "main"),
        ("https://www.reddit.com/r/singularity/.rss",          "reddit_sing",      "fringe"),
    ],
    "dark": [
        ("https://www.bleepingcomputer.com/feed/",             "bleepingcomputer", "main"),
        ("https://krebsonsecurity.com/feed/",                  "krebs_security",   "main"),
        ("https://www.darkreading.com/rss.xml",                "dark_reading",     "main"),
        ("https://www.schneier.com/feed/atom",                 "schneier",         "main"),
    ],
    "persons": [],  # HackerNews API sourced below
}

# ─── SIGNAL DATACLASS ────────────────────────────────────────────────────────

@dataclass
class HarvestedSignal:
    source_id:      str
    plane:          str
    content:        str
    title:          str
    url:            str
    raw_velocity:   float          # age-based freshness 0-1
    novelty_score:  float          # keyword density 0-1
    velocity_score: float = 0.0   # filled by caller (cluster velocity)
    cluster_id:     Optional[str] = None
    feed_tier:      str = "main"   # "main" | "fringe"


# ─── UTILITY ─────────────────────────────────────────────────────────────────

def _compute_source_id(url: str, title: str) -> str:
    """I·SRC — deterministic provenance hash."""
    payload = f"{url}:{title}"
    return "src:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def _recency_score(published_parsed, sweep_hours: int = 24) -> float:
    """
    Score freshness: 1.0 = just published, 0.0 = at edge of sweep window.
    """
    if not published_parsed:
        return 0.3   # unknown age — neutral
    try:
        pub_dt = datetime.datetime(*published_parsed[:6])
        age_h  = (datetime.datetime.utcnow() - pub_dt).total_seconds() / 3600
        score  = max(0.0, 1.0 - (age_h / sweep_hours))
        return round(score, 4)
    except Exception:
        return 0.3


def _keyword_density(text: str, keywords: list) -> float:
    """
    II·SCR — novelty score from keyword hit density.
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
) -> list:
    """Generic RSS harvester for a named plane."""
    sources  = RSS_SOURCES.get(plane, []) + (extra_feeds or [])
    signals  = []
    kw_set   = keywords or DEFAULT_KEYWORDS
    plane_kw = DOMAIN_KEYWORDS.get(plane, kw_set)

    for feed_url, feed_id, tier in sources:
        entries = _fetch_rss(feed_url)
        for entry in entries:
            title   = entry.get("title", "")
            content = entry.get("summary", entry.get("content", [{}])[0].get("value", ""))
            url     = entry.get("link", "")
            if not url:
                continue

            full_text  = f"{title} {content}"
            novelty    = _keyword_density(full_text, kw_set + plane_kw)
            recency    = _recency_score(entry.get("published_parsed"), sweep_hours)
            source_id  = _compute_source_id(url, title)

            signals.append(HarvestedSignal(
                source_id=source_id,
                plane=plane,
                content=content[:500],
                title=title,
                url=url,
                raw_velocity=recency,
                novelty_score=novelty,
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
        novelty  = _keyword_density(title, keywords or DEFAULT_KEYWORDS)
        source_id = _compute_source_id(url, title)
        rss_sigs.append(HarvestedSignal(
            source_id=source_id,
            plane="tech",
            content=content,
            title=title,
            url=url,
            raw_velocity=0.9,   # HN top = very fresh
            novelty_score=novelty,
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
        novelty  = _keyword_density(title, keywords or DEFAULT_KEYWORDS)
        source_id = _compute_source_id(url, title)
        sigs.append(HarvestedSignal(
            source_id=source_id,
            plane="persons",
            content=title,
            title=title,
            url=url,
            raw_velocity=0.8,
            novelty_score=novelty,
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
                "plane":         s.plane,
                "content":       s.content,
                "title":         s.title,
                "url":           s.url,
                "raw_velocity":  s.raw_velocity,
                "novelty_score": s.novelty_score,
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
