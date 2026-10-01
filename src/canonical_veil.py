"""Canonical Veil boundary adapter.

The MCP validates and projects caller-supplied Veil context. It does not
manufacture canonical runtime or epistemic events. Canonical Vault remains
authoritative for Veil runtime execution.
"""

from __future__ import annotations

from typing import Any


class CanonicalVeilBoundaryAdapter:
    """Validate/project Veil runtime context at the MCP boundary."""

    REQUIRED_IDENTITY = ("operator_id", "role", "sovereignty")
    REQUIRED_RUNTIME = ("altitude",)

    def validate(self, identity: dict[str, Any], runtime_state: dict[str, Any]) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for key in self.REQUIRED_IDENTITY:
            if identity.get(key) is None:
                errors.append(f"identity missing: {key}")
        for key in self.REQUIRED_RUNTIME:
            if runtime_state.get(key) is None:
                errors.append(f"runtime_state missing: {key}")
        return not errors, errors

    def project(self, identity: dict[str, Any], runtime_state: dict[str, Any]) -> dict[str, Any]:
        valid, errors = self.validate(identity, runtime_state)
        if not valid:
            raise ValueError("; ".join(errors))
        return {
            "identity": dict(identity),
            "runtime": dict(runtime_state),
            "authority": "canonical_veil",
            "canonical": True,
            "adapter_only": True,
        }

    def context(self, identity: dict[str, Any], runtime_state: dict[str, Any], seq: int | None = None) -> dict[str, Any]:
        """Return boundary context without emitting canonical events."""
        projected = self.project(identity, runtime_state)
        lineage = {
            "operator_id": identity["operator_id"],
            "role": identity["role"],
            "altitude": runtime_state["altitude"],
        }
        if seq is not None:
            lineage["seq"] = seq
        return {
            "identity": projected["identity"],
            "runtime": projected["runtime"],
            "authority": projected["authority"],
            "canonical": projected["canonical"],
            "adapter_only": projected["adapter_only"],
            "lineage": lineage,
        }
