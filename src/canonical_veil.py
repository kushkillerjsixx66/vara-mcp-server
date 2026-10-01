"""Canonical Veil boundary adapter for the Vara MCP portal.

This module does not implement a second Veil. It validates and projects the
runtime-boundary contract so the MCP can carry canonical Veil state without
claiming authority over the canonical runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


REQUIRED_IDENTITY = ("operator_id", "role", "sovereignty")
REQUIRED_RUNTIME = ("altitude",)


@dataclass
class CanonicalVeilBoundaryAdapter:
    """Contract adapter for Veil -> Stumpy -> Vara runtime mediation."""

    def validate(
        self,
        identity: dict[str, Any],
        runtime_state: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for key in REQUIRED_IDENTITY:
            if identity.get(key) is None:
                errors.append(f"identity missing: {key}")
        for key in REQUIRED_RUNTIME:
            if runtime_state.get(key) is None:
                errors.append(f"runtime_state missing: {key}")
        return not errors, errors

    def adapt(
        self,
        identity: dict[str, Any],
        runtime_state: dict[str, Any],
    ) -> dict[str, Any]:
        valid, errors = self.validate(identity, runtime_state)
        if not valid:
            raise ValueError("; ".join(errors))

        state = dict(runtime_state)
        return {
            "identity": dict(identity),
            "runtime_state": state,
            "authority": "canonical_veil",
            "canonical": True,
        }

    def events(
        self,
        identity: dict[str, Any],
        runtime_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        adapted = self.adapt(identity, runtime_state)
        runtime_event = {
            "type": "runtime_state",
            "source": "veil",
            "payload": {
                "identity": adapted["identity"],
                **adapted["runtime_state"],
            },
        }

        # The epistemic event is a portal projection. Canonical Vara remains
        # authoritative for actual supervisor execution and lineage state.
        lineage = [{
            "seq": 1,
            "operator_id": identity["operator_id"],
            "role": identity["role"],
            "altitude": runtime_state["altitude"],
        }]
        epistemic_event = {
            "type": "epistemic_state",
            "source": "vara",
            "payload": {
                "identity": adapted["identity"],
                "runtime": adapted["runtime_state"],
                "lineage": lineage,
            },
        }
        return [runtime_event, epistemic_event]
