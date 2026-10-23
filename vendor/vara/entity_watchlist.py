"""
Entity Watchlist + First-Seen Scoring for Vara
Operator: JRM-01 @liminaljermo

Tracks labs, models, protocols, chips, statutes, institutes.
First-seen scoring boosts novelty when an entity appears for the first time.
"""

from __future__ import annotations
import json
import os
import datetime
from typing import Optional, Set, Dict, List

WATCHLIST_PATH = "entity_watchlist_state.json"

# Default tracked entities (labs, models, protocols, chips, statutes)
DEFAULT_ENTITIES = {
    "labs": [
        "OpenAI", "Anthropic", "Google DeepMind", "DeepMind", "Meta AI", "Microsoft Research",
        "xAI", "Mistral", "Cohere", "Inflection", "Adept", "Character.AI", "Perplexity",
    ],
    # Companies tracked for entity-targeted scans (operator directive
    # 2026-10-23: the AI majors watch set).
    "companies": [
        "Microsoft", "Google", "NVIDIA", "Dell", "IBM", "OpenAI", "Anthropic",
        "xAI", "Perplexity", "Meta", "Amazon", "Apple",
    ],
    "models": [
        "GPT-4", "GPT-5", "Claude", "Gemini", "Llama", "Mistral", "Grok", "o1", "o3",
        "Qwen", "DeepSeek", "Command R", "ChatGPT", "NotebookLM",
        "Microsoft Copilot", "Copilot",
    ],
    "protocols": [
        "MCP", "Model Context Protocol", "A2A", "Agent2Agent", "OpenAI API", "Anthropic API",
    ],
    "chips": [
        "H100", "H200", "B200", "GB200", "Blackwell", "MI300", "TPU v5", "Trainium",
    ],
    "statutes": [
        "EU AI Act", "Executive Order 14110", "NIST AI RMF", "SB 1047",
    ],
}


def _flatten_entities(groups: dict = None) -> Set[str]:
    groups = groups or DEFAULT_ENTITIES
    out = set()
    for items in groups.values():
        for e in items:
            out.add(e.lower())
    return out


def load_first_seen_state() -> Dict[str, str]:
    if not os.path.exists(WATCHLIST_PATH):
        return {}
    try:
        with open(WATCHLIST_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_first_seen_state(state: dict) -> None:
    with open(WATCHLIST_PATH, "w") as f:
        json.dump(state, f, indent=2)


def score_entity_first_seen(
    text: str,
    state: Optional[dict] = None,
    boost: float = 0.12,
) -> tuple:
    """
    Scan text for watchlist entities. Return (boost_amount, newly_seen_list).
    First-seen entities get a novelty boost and are recorded in state.
    """
    if state is None:
        state = load_first_seen_state()
    entities = _flatten_entities()
    lower = (text or "").lower()
    newly_seen = []
    total_boost = 0.0
    now = datetime.datetime.utcnow().isoformat()

    for ent in entities:
        if ent in lower:
            key = ent
            if key not in state:
                state[key] = now
                newly_seen.append(ent)
                total_boost += boost

    if newly_seen:
        save_first_seen_state(state)

    return round(min(0.35, total_boost), 4), newly_seen


def enrich_signal_with_entities(signal: dict, state: Optional[dict] = None) -> dict:
    """Add entity first-seen boost to a signal's novelty_score."""
    text = f"{signal.get('title', '')} {signal.get('content', '')}"
    boost, newly = score_entity_first_seen(text, state=state)
    if boost > 0:
        signal = dict(signal)
        signal["novelty_score"] = round(min(1.0, float(signal.get("novelty_score", 0)) + boost), 4)
        signal["entity_first_seen"] = newly
        signal["entity_boost"] = boost
    return signal


# ─── True entity targeting (operator directive 2026-10-23) ──────────────────
#
# The canonical harvesters score keyword *relevance* but never filter: a
# scan "targeting" an entity used to return mostly plane-generic material.
# The helpers below give the server a strict entity layer of its own:
# word-boundary matching, per-entity news feeds (domains), and the default
# keyword set for untargeted scans.

import re
from urllib.parse import quote_plus

_ENTITY_PATTERNS: Dict[str, "re.Pattern"] = {}


def _entity_pattern(entity: str) -> "re.Pattern":
    key = entity.lower()
    pat = _ENTITY_PATTERNS.get(key)
    if pat is None:
        pat = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(entity) + r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
        _ENTITY_PATTERNS[key] = pat
    return pat


def match_entities(text: str, entities) -> List[str]:
    """Return the subset of `entities` named in `text`.

    Word-boundary aware (unlike the substring scan in
    score_entity_first_seen): "Dell" does not match "della", "Grok" does
    not match "grokking", "IBM" matches "IBM announced".
    """
    if not text or not entities:
        return []
    return [e for e in entities if _entity_pattern(str(e)).search(text)]


# Official newsroom / blog RSS feeds, keyed by lowercase entity name.
# Only feeds verified live are listed; every targeted entity additionally
# receives a Google News query feed (see entity_feed_urls), which is the
# guaranteed on-entity source.
ENTITY_OFFICIAL_FEEDS = {
    "google": ["https://blog.google/rss/"],
    "nvidia": ["https://blogs.nvidia.com/feed/"],
    "openai": ["https://openai.com/news/rss.xml"],
}

# Google News query per entity — disambiguated where the bare name is
# ambiguous or product-scoped.
ENTITY_NEWS_QUERIES = {
    "microsoft": "Microsoft AI",
    "google": "Google AI",
    "dell": "Dell Technologies",
    "grok": "Grok xAI",
    "copilot": "Microsoft Copilot",
    "microsoft copilot": "Microsoft Copilot",
    "notebooklm": "NotebookLM",
    "gemini": "Google Gemini",
}

_GOOGLE_NEWS_TEMPLATE = (
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
)


def entity_feed_urls(entities) -> List[str]:
    """Harvest domains for targeted entities: one Google News query feed
    per entity plus any verified official newsroom feeds. Deduped,
    order-preserving."""
    urls: List[str] = []
    for entity in entities or []:
        name = str(entity).strip()
        if not name:
            continue
        query = ENTITY_NEWS_QUERIES.get(name.lower(), name)
        urls.append(_GOOGLE_NEWS_TEMPLATE.format(query=quote_plus(query)))
        urls.extend(ENTITY_OFFICIAL_FEEDS.get(name.lower(), []))
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


# Default keyword set for scans that pass no keywords of their own:
# the tracked entity names plus the core topical vocabulary.
DEFAULT_SCAN_KEYWORDS = [
    "Microsoft", "Google", "NVIDIA", "Dell", "IBM", "OpenAI", "Anthropic",
    "xAI", "Perplexity", "Gemini", "Grok", "Microsoft Copilot", "NotebookLM",
    "ChatGPT", "Claude",
    "AI", "artificial intelligence", "LLM", "agentic AI", "AI agents",
    "inference", "GPU", "data center", "machine learning", "AI regulation",
]
