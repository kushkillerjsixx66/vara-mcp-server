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
    "models": [
        "GPT-4", "GPT-5", "Claude", "Gemini", "Llama", "Mistral", "Grok", "o1", "o3",
        "Qwen", "DeepSeek", "Command R",
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
