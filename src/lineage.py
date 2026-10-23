"""Per-signal lineage emission (Defect C, consolidated redeploy).

Operator standard (2026-09-29): per-signal provenance — source + retrieved
timestamp + disposition — is the precondition for any lineage-tracked
workflow. The inaugural scan record carried a source identifier only:
``canonical.lineage`` was emitted as ``[]``, pruned/deferred signals were
absent from the record, and ``lineage_present`` evaluated false.

This module is emission-only. It stamps the fields at the points where the
values already exist:

- ``source``        — the signal's source identifier (existing source_id,
                      falling back to its URL).
- ``retrieved_at``  — the harvest-time timestamp the vendor pipeline stamps
                      on each signal; for records produced by older builds
                      it falls back to the scan timestamp and is marked
                      with ``retrieved_at_basis="scan_timestamp"`` so the
                      fallback is never passed off as a per-feed time.
- ``disposition``   — the sentinel/Veil routing verdict recorded on the
                      signal itself, and on every harvested signal in
                      ``all_signals`` — including blocked / pruned /
                      deferred / veil-held signals, which previously
                      vanished from the record (weak-signal preservation,
                      VI·SIG: marked, not dropped).
- ``content_hash``  — SHA-256 of the signal content as retrieved, so
                      scan-to-scan drift compares bytes, not titles.

It also builds ``signal_lineage``: per-signal entries chaining
source -> scan_id -> disposition. That is *provenance* lineage. It does not
manufacture canonical (operator) lineage — promotion stays gated on
caller-supplied canonical lineage in ``canonical_vara``.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Optional

# Routing states (vendor ``routing.state_lineage``) -> record disposition.
_STATE_TO_DISPOSITION = {
    "HARVESTED": "harvested",
    "PASSED": "passed",
    "BLOCKED": "blocked",
    "PRUNED": "pruned",
    "DEFERRED": "deferred",
    "PROMOTED": "promoted",
    "HELD": "veil_held",
    "VAULT_BOUND": "vault_bound",
    "VEIL_HELD": "veil_held",
    "VEIL_PROMOTED": "promoted",
    "BELOW_FLOOR": "pruned",
}


def content_hash_for(signal: dict[str, Any]) -> str:
    """SHA-256 of the signal content as retrieved (title+URL fallback)."""
    content = signal.get("content")
    if content:
        payload = str(content)
    else:
        payload = f"{signal.get('title') or ''}\n{signal.get('url') or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def signal_source(signal: dict[str, Any]) -> str:
    return str(signal.get("source") or signal.get("source_id") or signal.get("url") or "")


def enrich_signal(
    signal: dict[str, Any],
    *,
    retrieved_at: str,
    disposition: Optional[str] = None,
) -> dict[str, Any]:
    """Stamp provenance fields on one signal (in place, idempotent)."""
    if not signal.get("source"):
        source = signal_source(signal)
        if source:
            signal["source"] = source
    if not signal.get("retrieved_at"):
        signal["retrieved_at"] = retrieved_at
        signal.setdefault("retrieved_at_basis", "scan_timestamp")
    if not signal.get("content_hash") and signal.get("body_recorded") is not False:
        signal["content_hash"] = content_hash_for(signal)
    if disposition and not signal.get("disposition"):
        signal["disposition"] = disposition
    return signal


def _disposition_map(report: dict[str, Any]) -> dict[str, str]:
    """signal_id/source_id -> disposition, from every routing record present."""
    out: dict[str, str] = {}
    routing = report.get("routing") or {}
    for entry in routing.get("state_lineage") or []:
        if not isinstance(entry, dict):
            continue
        state = str(entry.get("state") or "").upper()
        disp = _STATE_TO_DISPOSITION.get(state)
        if not disp:
            continue
        for key in (entry.get("signal_id"), entry.get("source_id")):
            if key:
                out.setdefault(str(key), disp)
    return out


def _extra_collections(report: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield harvested-signal collections a pipeline may embed in a report."""
    for key in ("all_signals", "weak_signals"):
        for sig in report.get(key) or []:
            if isinstance(sig, dict):
                yield sig
    sentinel = report.get("sentinel") or {}
    if isinstance(sentinel, dict):
        for key in ("passed_signals", "blocked_signals", "pruned_signals", "deferred_signals"):
            for sig in sentinel.get(key) or []:
                if isinstance(sig, dict):
                    yield sig


def enrich_report(report: dict[str, Any]) -> dict[str, Any]:
    """Add per-signal provenance, ``all_signals`` and ``signal_lineage``.

    Mutates and returns *report*. ``all_signals`` is the full harvested set
    as far as the pipeline recorded it: output signals plus every
    blocked/pruned/deferred/veil-held record the report carries (embedded
    collections or ``routing.state_lineage`` identities). A signal that the
    pipeline recorded only as a routing identity appears as a provenance
    record with its disposition — present, marked, not dropped.
    """
    scan_id = str(report.get("scan_id") or "")
    retrieved_at = str(report.get("timestamp") or "")
    dispositions = _disposition_map(report)

    def disposition_for(sig: dict[str, Any], default: str = "vault_bound") -> str:
        if sig.get("disposition"):
            return str(sig["disposition"])
        for key in (sig.get("signal_id"), sig.get("source_id")):
            if key and str(key) in dispositions:
                return dispositions[str(key)]
        return default

    # 1. Output signals carry full provenance.
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _key(sig: dict[str, Any]) -> tuple[str, str]:
        return (
            str(sig.get("signal_id") or sig.get("source_id") or ""),
            str(sig.get("observation_id") or sig.get("url") or ""),
        )

    for sig in report.get("signals") or []:
        if not isinstance(sig, dict):
            continue
        enrich_signal(sig, retrieved_at=retrieved_at, disposition=disposition_for(sig))
        output.append(sig)
        seen.add(_key(sig))

    # 2. The full harvested set: every other recorded signal joins with its
    #    disposition instead of being absent.
    all_signals: list[dict[str, Any]] = list(output)
    for sig in _extra_collections(report):
        if _key(sig) in seen:
            # Same dict may already be enriched above; ensure disposition.
            if not sig.get("disposition"):
                enrich_signal(sig, retrieved_at=retrieved_at, disposition=disposition_for(sig, "harvested"))
            continue
        enrich_signal(sig, retrieved_at=retrieved_at, disposition=disposition_for(sig, "harvested"))
        all_signals.append(sig)
        seen.add(_key(sig))

    # 3. Routing identities with no body anywhere in the report (the classic
    #    pruned/deferred case) still get a provenance record.
    routing = report.get("routing") or {}
    seen_ids = {
        str(s.get("signal_id") or s.get("source_id") or "")
        for s in all_signals
    }
    for entry in routing.get("state_lineage") or []:
        if not isinstance(entry, dict):
            continue
        key = (
            str(entry.get("signal_id") or entry.get("source_id") or ""),
            str(entry.get("observation_id") or ""),
        )
        if not key[0] or key in seen or (not key[1] and key[0] in seen_ids):
            continue
        state = str(entry.get("state") or "").upper()
        record = {
            "signal_id": entry.get("signal_id"),
            "source_id": entry.get("source_id"),
            "source": entry.get("source_id") or "",
            "observation_id": entry.get("observation_id"),
            "retrieved_at": retrieved_at,
            "retrieved_at_basis": "scan_timestamp",
            "disposition": _STATE_TO_DISPOSITION.get(state, "harvested"),
            "content_hash": None,
            "body_recorded": False,
        }
        all_signals.append(record)
        seen.add(key)
        seen_ids.add(key[0])

    report["all_signals"] = all_signals

    # 4. Per-signal lineage: source -> scan_id -> disposition.
    lineage: list[dict[str, Any]] = []
    for sig in all_signals:
        lineage.append(
            {
                "kind": "signal_provenance",
                "signal_id": sig.get("signal_id") or sig.get("source_id"),
                "source": signal_source(sig),
                "source_id": sig.get("source_id"),
                "url": sig.get("url"),
                "scan_id": scan_id,
                "retrieved_at": sig.get("retrieved_at"),
                "disposition": sig.get("disposition"),
                "content_hash": sig.get("content_hash"),
            }
        )
    report["signal_lineage"] = lineage
    return report
