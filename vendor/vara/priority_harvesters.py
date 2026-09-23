"""
Priority-1 API Harvesters for Vara
Operator: JRM-01 @liminaljermo

- arXiv API (cs.AI / cs.LG / cs.CL / cs.CR)
- Federal Register (AI / export / compute)
- GitHub releases + agent/MCP topics
"""

from __future__ import annotations
import hashlib
import logging
from typing import List, Optional
from dataclasses import dataclass

logger = logging.getLogger("vara.priority")

try:
    import requests
    _NET = True
except ImportError:
    _NET = False


def _sid(url: str, title: str) -> str:
    return "src:" + hashlib.sha256(f"{url}:{title}".encode()).hexdigest()[:16]


def _sig(plane: str, title: str, content: str) -> str:
    return "sig:" + hashlib.sha256(f"{plane}:{title} {content}"[:2000].encode()).hexdigest()[:16]


def harvest_arxiv(keywords: list, max_results: int = 30) -> list:
    if not _NET:
        return []
    signals = []
    cats = ["cs.AI", "cs.LG", "cs.CL", "cs.CR"]
    for cat in cats:
        try:
            url = f"http://export.arxiv.org/api/query?search_query=cat:{cat}&start=0&max_results={max_results // len(cats)}&sortBy=submittedDate&sortOrder=descending"
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            # Minimal parse without feedparser dependency for API XML
            text = r.text
            entries = text.split("<entry>")[1:]
            for ent in entries[:8]:
                title = ""
                if "<title>" in ent:
                    title = ent.split("<title>")[1].split("</title>")[0].strip()
                link = ""
                if "http://arxiv.org/abs/" in ent:
                    link = "http://arxiv.org/abs/" + ent.split("http://arxiv.org/abs/")[1].split("<")[0].split("\"")[0]
                summary = ""
                if "<summary>" in ent:
                    summary = ent.split("<summary>")[1].split("</summary>")[0].strip()[:400]
                if not title:
                    continue
                lower = f"{title} {summary}".lower()
                hits = sum(1 for kw in (keywords or ["AI"]) if kw.lower() in lower)
                novelty = min(1.0, 0.1 + hits * 0.08)
                signals.append({
                    "source_id": _sid(link or title, title),
                    "signal_id": _sig("scientific", title, summary),
                    "observation_id": "obs:arxiv:" + hashlib.sha256(title.encode()).hexdigest()[:12],
                    "plane": "scientific",
                    "title": title,
                    "content": summary,
                    "url": link,
                    "raw_velocity": 0.8,
                    "novelty_score": round(novelty, 4),
                    "feed_tier": "main",
                })
        except Exception as e:
            logger.warning("arXiv harvest failed %s: %s", cat, e)
    return signals


def harvest_github_agent_topics(keywords: list, max_results: int = 20) -> list:
    if not _NET:
        return []
    signals = []
    try:
        # Public search — may rate-limit without token
        q = "MCP OR agentic OR \"model context protocol\" in:name,description"
        r = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": q, "sort": "updated", "per_page": min(max_results, 15)},
            headers={"Accept": "application/vnd.github+json", "User-Agent": "VaraPriority/1.0"},
            timeout=12,
        )
        if r.status_code != 200:
            return []
        for item in r.json().get("items", []):
            title = item.get("full_name", "")
            desc = (item.get("description") or "")[:300]
            url = item.get("html_url", "")
            signals.append({
                "source_id": _sid(url, title),
                "signal_id": _sig("tech", title, desc),
                "observation_id": "obs:gh:" + str(item.get("id", "")),
                "plane": "tech",
                "title": title,
                "content": desc,
                "url": url,
                "raw_velocity": 0.75,
                "novelty_score": 0.18,
                "feed_tier": "main",
            })
    except Exception as e:
        logger.warning("GitHub harvest failed: %s", e)
    return signals


def harvest_priority(keywords: list, **kwargs) -> list:
    """Run all priority-1 harvesters and return combined signals."""
    out = []
    out.extend(harvest_arxiv(keywords))
    out.extend(harvest_github_agent_topics(keywords))
    return out
