"""Canonical Vara conformance adapter for the MCP operational scan.

The MCP deployment is a portal into Vara, not a second Vault implementation.
This module projects the operational scan into the canonical VaraScanResult
shape and applies the canonical integrity/promotion rules. It emits a
canonical promotion event for the governed Vault pipeline; it does not write
a local pseudo-Vault.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


REQUIRED_LINEAGE = ("seq", "operator_id", "role", "altitude")


@dataclass
class CanonicalVaraScanResult:
    weak_signals: list[dict[str, Any]]
    trends: list[dict[str, Any]]
    anomalies: list[dict[str, Any]]
    unspecified: list[str]
    lineage: list[dict[str, Any]]


class CanonicalVaraIntegrity:
    """Mirror the canonical VaultScanIntegrity contract."""

    def validate(self, scan: CanonicalVaraScanResult) -> tuple[bool, list[str]]:
        errors: list[str] = []

        if not scan.lineage:
            errors.append("lineage is required for canonical Vara status")

        for index, entry in enumerate(scan.lineage):
            missing = [key for key in REQUIRED_LINEAGE if key not in entry]
            if missing:
                errors.append(f"lineage[{index}] missing: {','.join(missing)}")

        for index, signal in enumerate(scan.weak_signals):
            if not signal.get("key") or not signal.get("description"):
                errors.append(f"weak_signals[{index}] missing key/description")
            if "evidence" not in signal:
                errors.append(f"weak_signals[{index}] missing evidence")

        for index, anomaly in enumerate(scan.anomalies):
            if not anomaly.get("field") or "value" not in anomaly or anomaly.get("reason") is None:
                errors.append(f"anomalies[{index}] missing field/value/reason")

        return not errors, errors


class CanonicalVaraPromoter:
    """Mirror the canonical VaultScanPromoter contract."""

    def should_promote(self, scan: CanonicalVaraScanResult) -> bool:
        if not scan.lineage:
            return False
        if scan.weak_signals or scan.anomalies:
            return True
        return False


def _signal_to_weak(signal: dict[str, Any], index: int) -> dict[str, Any]:
    key = str(signal.get("signal_id") or signal.get("source_id") or f"signal-{index}")
    description = str(
        signal.get("content") or signal.get("title") or "Operational Vara signal"
    )
    evidence = (
        signal.get("source_url")
        or signal.get("source_id")
        or signal.get("observation_id")
        or ""
    )
    return {"key": key, "description": description, "evidence": evidence}


def project_operational_report(
    report: dict[str, Any],
    lineage: list[dict[str, Any]] | None,
) -> tuple[CanonicalVaraScanResult, list[str]]:
    """Project operational output into the canonical VaraScanResult shape."""
    signals = report.get("signals") or []
    canonical = CanonicalVaraScanResult(
        weak_signals=[
            _signal_to_weak(signal, index)
            for index, signal in enumerate(signals)
            if isinstance(signal, dict)
        ],
        trends=[
            {
                "name": cluster.get("cluster_id") or f"cluster-{index}",
                "signals": cluster.get("members") or cluster.get("signal_ids") or [],
            }
            for index, cluster in enumerate(report.get("clusters") or [])
            if isinstance(cluster, dict)
        ],
        anomalies=[],
        unspecified=[
            "operational scan returned null result"
        ] if report.get("null_result") else [],
        lineage=list(lineage or []),
    )
    return canonical, []


def govern_operational_report(
    report: dict[str, Any],
    lineage: list[dict[str, Any]] | None,
    store_root: str | None = None,
) -> dict[str, Any]:
    """Apply canonical integrity/promotion semantics without local Vault writes.

    store_root is retained as a compatibility argument for the current MCP
    call path. It is intentionally ignored. Canonical persistence belongs
    to the governed Vault scan pipeline.
    """
    del store_root

    canonical, _ = project_operational_report(report, lineage)
    valid, errors = CanonicalVaraIntegrity().validate(canonical)
    promotion_allowed = valid and CanonicalVaraPromoter().should_promote(canonical)

    result = dict(report)
    result["canonical"] = {
        "weak_signals": canonical.weak_signals,
        "trends": canonical.trends,
        "anomalies": canonical.anomalies,
        "unspecified": canonical.unspecified,
        "lineage": canonical.lineage,
    }
    result["canonical_conformance"] = {
        "lineage_present": bool(canonical.lineage),
        "integrity_valid": valid,
        "promotion_allowed": promotion_allowed,
        "errors": errors,
    }

    if promotion_allowed:
        result["canonical_conformance"]["promotion_event"] = {
            "type": "vault_promotion",
            "source": "vara_scan_pipeline",
            "payload": {
                "lineage": canonical.lineage,
                "scan": result["canonical"],
            },
            "dispatch": "canonical_vault_pipeline_required",
        }

    return result
