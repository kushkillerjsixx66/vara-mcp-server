"""True entity targeting (operator directive 2026-10-23).

The canonical harvesters score keyword relevance but never filter, so an
entity-"targeted" scan used to return plane-generic material. The server
now owns a strict entity layer: word-boundary matching in
entity_watchlist, a post-enrichment filter stage in vara_scan, per-entity
harvest domains (Google News query feed + verified official feeds), and
an updated default keyword set.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VENDOR = str(ROOT / "vendor" / "vara")
if VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)

import entity_watchlist as ew  # noqa: E402
import vara_scan  # noqa: E402


# ─── match_entities: word boundaries, not substrings ─────────────────────────

def test_match_entities_word_boundaries():
    text = "Dell Technologies reported earnings; della roberts kept grokking the codebase"
    assert ew.match_entities(text, ["Dell", "Grok"]) == ["Dell"]


def test_match_entities_case_insensitive_and_multiword():
    text = "microsoft copilot rolled out; IBM announced a chip"
    assert ew.match_entities(text, ["Microsoft Copilot", "IBM"]) == [
        "Microsoft Copilot",
        "IBM",
    ]


def test_match_entities_empty_inputs():
    assert ew.match_entities("", ["IBM"]) == []
    assert ew.match_entities("IBM", []) == []


# ─── entity_feed_urls: domains per entity ────────────────────────────────────

def test_entity_feed_urls_google_news_and_official():
    urls = ew.entity_feed_urls(["OpenAI", "Dell", "Copilot"])
    assert any("news.google.com" in u and "OpenAI" in u for u in urls)
    assert "https://openai.com/news/rss.xml" in urls
    assert any("Dell+Technologies" in u for u in urls)
    assert any("Microsoft+Copilot" in u for u in urls)
    assert len(urls) == len(set(urls))


def test_watchlist_registries_cover_operator_set():
    flat = ew._flatten_entities()
    for name in ("microsoft", "google", "nvidia", "dell", "ibm", "openai",
                 "anthropic", "perplexity", "gemini", "grok", "notebooklm",
                 "microsoft copilot"):
        assert name in flat, name
    for name in ("Microsoft", "NVIDIA", "OpenAI", "Gemini", "NotebookLM"):
        assert name in ew.DEFAULT_SCAN_KEYWORDS, name


# ─── stage_entity_filter ─────────────────────────────────────────────────────

def _sig(title, content, novelty=0.5):
    return {
        "source_id": "src:test", "plane": "tech", "title": title,
        "content": content, "url": "https://a.example/x",
        "novelty_score": novelty, "raw_velocity": 0.5, "feed_tier": "main",
    }


def test_stage_entity_filter_keeps_only_named_entities():
    signals = [
        _sig("NVIDIA unveils a chip", "datacenter demand"),
        _sig("A small model asks better", "retrieval research at a lab"),
        _sig("della's kitchen diary", "recipes"),
    ]
    kept, stats = vara_scan.stage_entity_filter(signals, ["NVIDIA", "Dell"])
    assert len(kept) == 1
    assert kept[0]["matched_entities"] == ["NVIDIA"]
    assert stats["pre_filter"] == 3
    assert stats["kept"] == 1
    assert stats["dropped"] == 2
    assert stats["per_entity"] == {"NVIDIA": 1}


# ─── run_vara_scan end-to-end with a canned harvest ──────────────────────────

def test_targeted_scan_filters_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(vara_scan, "OUTPUT_DIR", str(tmp_path / "out"))
    canned = [
        _sig("OpenAI ships a model", "OpenAI announced it today", novelty=0.6),
        _sig("Generic ML paper", "a study of retrieval methods", novelty=0.6),
        _sig("Chip demand rises", "NVIDIA supply tightens", novelty=0.6),
    ]
    monkeypatch.setattr(
        vara_scan, "stage_intake", lambda cfg: (list(canned), [])
    )
    cfg = vara_scan.VaraConfig(
        keywords=["AI"], sweep_depth_hours=24, active_planes=["tech"],
        scan_label="entity-test", target_entities=["OpenAI", "NVIDIA"],
    )
    report = vara_scan.run_vara_scan(cfg)
    assert report.entity_filter is not None
    assert report.entity_filter["pre_filter"] == 3
    assert report.entity_filter["kept"] == 2
    assert report.entity_filter["dropped"] == 1
    assert report.routing["entity_filter"]["kept"] == 2
    titles = [s["title"] for s in report.all_signals]
    assert "Generic ML paper" not in titles
    assert all("matched_entities" in s for s in report.all_signals)


def test_targeted_scan_all_filtered_is_null_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(vara_scan, "OUTPUT_DIR", str(tmp_path / "out"))
    canned = [_sig("Generic ML paper", "nothing named here", novelty=0.6)]
    monkeypatch.setattr(
        vara_scan, "stage_intake", lambda cfg: (list(canned), [])
    )
    cfg = vara_scan.VaraConfig(
        keywords=["AI"], sweep_depth_hours=24, active_planes=["tech"],
        scan_label="entity-test-empty", target_entities=["OpenAI"],
    )
    report = vara_scan.run_vara_scan(cfg)
    assert report.null_result is True
    assert report.signals == []
    assert report.entity_filter["dropped"] == 1


def test_untargeted_scan_has_no_entity_filter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(vara_scan, "OUTPUT_DIR", str(tmp_path / "out"))
    canned = [_sig("Generic ML paper", "a study", novelty=0.6)]
    monkeypatch.setattr(
        vara_scan, "stage_intake", lambda cfg: (list(canned), [])
    )
    cfg = vara_scan.VaraConfig(
        keywords=["AI"], sweep_depth_hours=24, active_planes=["tech"],
        scan_label="plain-test",
    )
    report = vara_scan.run_vara_scan(cfg)
    assert report.entity_filter is None
    assert len(report.all_signals) == 1
