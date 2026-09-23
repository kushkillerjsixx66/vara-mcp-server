"""
VARA Veil + Vault — Mediation and Persistence Layer (MCP vendor copy)
"""
from __future__ import annotations
import json, os, datetime, hashlib, uuid
from dataclasses import dataclass
from typing import Optional

VEIL_HOLD_PATH = "veil_hold.json"
VAULT_PATH = "vault_signals.json"
VEIL_RECURRENCE_THRESHOLD = 2
VEIL_MISSED_SCAN_TTL = 3

@dataclass
class VeilReport:
    veil_id: str
    scan_id: str
    timestamp: str
    held_incoming: int
    promoted: int
    held_over: int
    expired: int
    promoted_signals: list
    held_entries: list

@dataclass
class VaultReport:
    vault_id: str
    scan_id: str
    timestamp: str
    committed: int
    total_vault_size: int
    new_entries: list

def load_veil_hold() -> dict:
    if not os.path.exists(VEIL_HOLD_PATH):
        return {}
    try:
        with open(VEIL_HOLD_PATH) as f:
            return json.load(f)
    except Exception:
        return {}

def save_veil_hold(hold: dict) -> None:
    with open(VEIL_HOLD_PATH, "w") as f:
        json.dump(hold, f, indent=2)

def load_vault() -> list:
    if not os.path.exists(VAULT_PATH):
        return []
    try:
        with open(VAULT_PATH) as f:
            return json.load(f)
    except Exception:
        return []

def save_vault(entries: list) -> None:
    with open(VAULT_PATH, "w") as f:
        json.dump(entries, f, indent=2)

def commit_to_vault(signals: list, scan_id: str, origin: str = "passed") -> VaultReport:
    vault = load_vault()
    timestamp = datetime.datetime.utcnow().isoformat()
    new_entries = []
    existing_ids = {e.get("signal_id") for e in vault}
    for sig in signals:
        sid = sig.get("signal_id") or sig.get("source_id") or str(uuid.uuid4())
        if sid in existing_ids:
            continue
        vault_id = hashlib.sha256(f"{sid}:{scan_id}:{timestamp}".encode()).hexdigest()[:24]
        entry = {
            "vault_id": vault_id, "source_id": sig.get("source_id", ""),
            "observation_id": sig.get("observation_id", ""), "signal_id": sid,
            "scan_id": scan_id, "committed_at": timestamp, "signal": sig,
            "origin": origin, "canonized": False,
        }
        vault.append(entry)
        new_entries.append(entry)
    save_vault(vault)
    return VaultReport(str(uuid.uuid4()), scan_id, timestamp, len(new_entries), len(vault), new_entries)

def run_veil(deferred_signals: list, scan_id: str) -> VeilReport:
    hold = load_veil_hold()
    timestamp = datetime.datetime.utcnow().isoformat()
    promoted, expired = [], 0
    current_ids = {s.get("signal_id") or s.get("source_id") for s in deferred_signals}
    for sid, entry in list(hold.items()):
        if isinstance(entry, dict) and sid not in current_ids and entry.get("status") == "HELD":
            entry["missed_scans"] = entry.get("missed_scans", 0) + 1
            if entry["missed_scans"] >= VEIL_MISSED_SCAN_TTL:
                entry["status"] = "EXPIRED"
                expired += 1
    for sig in deferred_signals:
        sid = sig.get("signal_id") or sig.get("source_id") or str(uuid.uuid4())
        if sid in hold and isinstance(hold[sid], dict):
            entry = hold[sid]
            entry["recurrence_count"] = entry.get("recurrence_count", 1) + 1
            entry["consecutive_scans"] = entry.get("consecutive_scans", 1) + 1
            entry["missed_scans"] = 0
            entry["last_seen_scan"] = scan_id
            if entry.get("consecutive_scans", 0) >= VEIL_RECURRENCE_THRESHOLD:
                entry["status"] = "PROMOTED"
                promoted.append(sig)
        else:
            hold[sid] = {
                "source_id": sig.get("source_id", ""), "signal": sig,
                "signal_id": sid, "first_seen_scan": scan_id, "last_seen_scan": scan_id,
                "recurrence_count": 1, "consecutive_scans": 1, "missed_scans": 0, "status": "HELD",
            }
    hold = {k: v for k, v in hold.items() if isinstance(v, dict) and v.get("status") not in {"EXPIRED", "PROMOTED"}}
    save_veil_hold(hold)
    held_over = sum(1 for v in hold.values() if isinstance(v, dict) and v.get("status") == "HELD")
    return VeilReport(str(uuid.uuid4()), scan_id, timestamp, len(deferred_signals),
                      len(promoted), held_over, expired, promoted,
                      [v for v in hold.values() if isinstance(v, dict) and v.get("status") == "HELD"])

def route_signals(passed_signals: list, deferred_signals: list, scan_id: str) -> tuple:
    vault_report = commit_to_vault(passed_signals, scan_id, origin="passed")
    veil_report = run_veil(deferred_signals, scan_id)
    if veil_report.promoted_signals:
        promo = commit_to_vault(veil_report.promoted_signals, scan_id, origin="veil_promoted")
        vault_report.committed += promo.committed
        vault_report.total_vault_size = promo.total_vault_size
        vault_report.new_entries.extend(promo.new_entries)
    return vault_report, veil_report
