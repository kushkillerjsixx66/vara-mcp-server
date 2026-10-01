"""Canonical Veil boundary adapter.

The MCP exposes the canonical Veil contract without becoming a second Veil.
Canonical runtime authority remains in Canonical Vault.
"""

from __future__ import annotations

from typing import Any


class CanonicalVeilBoundaryAdapter:
    """Validate/project Veil runtime context at the MCP boundary."""

    REQUIRED_IDENTITY = ("operator_id", "role", "sovereignty")
    REQUIRED_RUNTIME = ("altitude",)

    def validate(
        self,
        identity: dict[str, Any],
        runtime_state: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for key in self.REQUIRED_IDENTITY:
            if identity.get(key) is None:
                errors.append(f"identity missing: {key}")
        for key in self.REQUIRED_RUNTIME:
            if runtime_state.get(key) is None:
                errors.append(f"runtime_state missing: {key}")
        return not errors, errors

    def project(
        self,
        identity: dict[str, Any],
        runtime_state: dict[str, Any],
    ) -> dict[str, Any]:
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

    def events(
        self,
        identity: dict[str, Any],
        runtime_state: dict[str, Any],
        seq: int = 1,
    ) -> list[dict[str, Any]]:
        context = self.project(identity, runtime_state)
        lineage = [{
            "seq": seq,
            "operator_id": identity["operator_id"],
            "role": identity["role"],
            "altitude": runtime_state["altitude"],
        }]

        return [
            {
                "type": "runtime_state",
                "source": "veil",
                "payload": {
                    "identity": context["identity"],
                    **context["runtime"],
                },
            },
            {
                "type": "epistemic_state",
                "source": "vara",
                "payload": {
                    "identity": context["identity"],
                    "runtime": context["runtime"],
                    "lineage": lineage,
                },
            },
        ]
