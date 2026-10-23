"""
VARA Veil + Vault — Mediation and Persistence Layer
Operator: JRM-01 @liminaljermo
Spec ref: Lattice Unified Spec §4, §8; Constitution Article VI

Signal routing:
  passed_signals   → Vault.commit() → Stumpy audit
  deferred_signals → Veil.hold()    → re-gate next cycle → Vault.commit()

Veil invariant (§4): prevents runaway recursion; softens divergence.
Vault invariant (Article VI): commit → review → canon lifecycle.
  No artifact may bypass the Vault.
  No canonized artifact may be deleted.

Reversibility First: deferred signals earn passage through recurrence,
not declaration. A signal recurring across 2+ consecutive scans passes Veil.
"""

import json
import os
import datetime
import hashlib
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

from vara_harvesters import _compute_signal_id

# ─── PATHS ───────────────────────────────────────────────────────────────────

VEIL_HOLD_PATH   = "veil_hold.json"       # deferred signals held between cycles
VAULT_PATH       = "vault_signals.json"   # committed signal store
VAULT_CANON_PATH = "vault_canon.json"     # canonized (immutable) signal store

# ─── RECURRENCE THRESHOLD ────────────────────────────────────────────────────
# A deferred signal must appear in N consecutive scans to earn Vault passage.

VEIL_RECURRENCE_THRESHOLD = 2
VEIL_MISSED_SCAN_TTL = 3

# ─── DATA STRUCTURES ─────────────────────────────────────────────────────────

@dataclass
class VeilEntry:
    source_id:        str
    signal:           dict
    first_seen_scan:  str
    last_seen_scan:   str
    observation_id:   str = ""
    signal_id:        str = ""
    recurrence_count: int  = 1
    consecutive_scans: int = 1
    missed_scans:     int  = 0
    status:           str  = "HELD"   # HELD | PROMOTED | EXPIRED


@dataclass
class VaultEntry:
    vault_id:     str
    source_id:    str
    observation_id: str
    signal_id:    str
    scan_id:      str
    committed_at: str
    signal:       dict
    origin:       str                    # "passed" | "veil_promoted"
    observations: list = field(default_factory=list)
    canonized:    bool           = False
    canonized_at: Optional[str] = None


@dataclass
class VeilReport:
    veil_id:          str
    scan_id:          str
    timestamp:        str
    held_incoming:    int
    promoted:         int
    held_over:        int
    expired:          int
    promoted_signals: list
    held_entries:     list


@dataclass
class VaultReport:
    vault_id:        str
    scan_id:         str
    timestamp:       str
    committed:       int
    total_vault_size: int
    new_entries:     list


# ─── VEIL ────────────────────────────────────────────────────────────────────

def load_veil_hold() -> dict:
    """Load held signals from prior cycles."""
    if not os.path.exists(VEIL_HOLD_PATH):
        return {}
    try:
        with open(VEIL_HOLD_PATH, "r") as f:
            raw = json.load(f)
        entries = {}
        for k, value in raw.items():
            # Older holds predate missed_scans. Default it during migration
            # rather than invalidating the entire persisted hold file.
            value.setdefault("missed_scans", 0)
            value.setdefault("consecutive_scans", 1 if value.get("recurrence_count", 1) else 0)
            entry = VeilEntry(**value)
            # Legacy holds predate signal_id. Reconstruct a lexical signal
            # identity so recurrence can migrate away from URL/title identity.
            if not entry.signal_id:
                entry.signal_id = _compute_signal_id(
                    entry.signal.get("plane", ""),
                    entry.signal.get("title", ""),
                    entry.signal.get("content", ""),
                )
            if not entry.observation_id:
                entry.observation_id = entry.signal.get("observation_id", "")
            entries[entry.signal_id or k] = entry
        return entries
    except (json.JSONDecodeError, TypeError, KeyError):
        return {}


def save_veil_hold(hold: dict) -> None:
    """Persist the current veil hold to disk."""
    serializable = {k: asdict(v) for k, v in hold.items()}
    with open(VEIL_HOLD_PATH, "w") as f:
        json.dump(serializable, f, indent=2)


def run_veil(deferred_signals: list, scan_id: str) -> VeilReport:
    """
    Process deferred signals through the Veil.

    - Signals seen on VEIL_RECURRENCE_THRESHOLD consecutive scans are
      PROMOTED to Vault.
    - New signals are HELD for next cycle.
    - Signals not seen in a scan increment missed_scans.
    - HELD signals expire after VEIL_MISSED_SCAN_TTL consecutive missed scans.

    Returns VeilReport with promoted_signals ready for Vault commit.
    """
    hold     = load_veil_hold()
    timestamp = datetime.datetime.utcnow().isoformat()
    promoted  = []
    expired   = 0

    # Track total recurrence, consecutive recurrence, and absence separately.
    # Promotion requires consecutive evidence, not merely cumulative sightings.
    current_ids = {
        s.get("signal_id") or _compute_signal_id(
            s.get("plane", ""), s.get("title", ""), s.get("content", "")
        )
        for s in deferred_signals
    }
    for sid, entry in list(hold.items()):
        if sid not in current_ids and entry.status == "HELD":
            entry.missed_scans += 1
            entry.consecutive_scans = 0
            if entry.missed_scans >= VEIL_MISSED_SCAN_TTL:
                entry.status = "EXPIRED"
                expired += 1

    # Process incoming deferred signals
    for sig in deferred_signals:
        sid = sig.get("signal_id") or _compute_signal_id(
            sig.get("plane", ""), sig.get("title", ""), sig.get("content", "")
        )

        if sid in hold:
            entry = hold[sid]
            entry.recurrence_count += 1
            entry.consecutive_scans += 1
            entry.missed_scans      = 0
            entry.last_seen_scan    = scan_id
            entry.signal            = sig   # refresh with latest version

            if entry.consecutive_scans >= VEIL_RECURRENCE_THRESHOLD:
                entry.status = "PROMOTED"
                promoted.append(sig)
        else:
            hold[sid] = VeilEntry(
                source_id=sig.get("source_id", ""),
                signal=sig,
                observation_id=sig.get("observation_id", ""),
                signal_id=sid,
                first_seen_scan=scan_id,
                last_seen_scan=scan_id,
                recurrence_count=1,
                consecutive_scans=1,
                missed_scans=0,
                status="HELD",
            )

    # Promoted entries have crossed the Veil boundary and no longer belong
    # in the deferred hold. Expired entries are likewise removed.
    hold = {k: v for k, v in hold.items() if v.status not in {"EXPIRED", "PROMOTED"}}
    save_veil_hold(hold)

    held_over = sum(1 for v in hold.values() if v.status == "HELD")

    return VeilReport(
        veil_id=str(uuid.uuid4()),
        scan_id=scan_id,
        timestamp=timestamp,
        held_incoming=len(deferred_signals),
        promoted=len(promoted),
        held_over=held_over,
        expired=expired,
        promoted_signals=promoted,
        held_entries=[asdict(v) for v in hold.values() if v.status == "HELD"],
    )


# ─── VAULT ───────────────────────────────────────────────────────────────────

def load_vault() -> list:
    """Load existing vault entries."""
    if not os.path.exists(VAULT_PATH):
        return []
    try:
        with open(VAULT_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []


def save_vault(entries: list) -> None:
    with open(VAULT_PATH, "w") as f:
        json.dump(entries, f, indent=2)
# ─── OPERATOR PORT NOTE (Fork 2, 2026-10-23) ─────────────────────────────
# This vendored copy of the canonical veil/vault module WITHHOLDS three
# canonical entry points, per the server repo's governance boundary
# (tests/test_canonical_vara.py: the operational layer records
# dispositions; it does not route or commit):
#   - route_signals        (canonical: scan-internal routing + commit)
#   - commit_to_vault      (canonical: immediate corpus commit)
#   - canonize_vault_entry (canonical: canonization)
# Everything else is canonical verbatim: Veil hold, trajectories,
# recurrence promotion REPORTING via run_veil (promotions surface as
# records for the governing layer; no write is performed here).
# ──────────────────────────────────────────────────────────────────────────
