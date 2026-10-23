"""
vara.py — Vara Core Entry Point
Operator: JRM-01 @liminaljermo
Spec ref: Lattice Unified Spec §3

The Vara class is the lattice-facing interface for the signal acquisition
and mediation subsystem.  It delegates all scan work to vara_scan.py and
exposes a single run() method to the lattice runtime.
"""

import datetime
import json
from dataclasses import asdict


class Vara:
    """
    Top-level Vara runtime object.

    Parameters
    ----------
    lattice : object
        Reference to the parent Lattice runtime (passed by the boot loader).
        Used for callback hooks; may be None in standalone mode.
    """

    VERSION = "1.2.0"

    def __init__(self, lattice=None):
        self.lattice     = lattice
        self.last_scan   = None
        self._scan_count = 0

    # ── Public API ──────────────────────────────────────────────────────────

    def run(self, config=None) -> dict:
        """
        Execute one Vara scan cycle.

        Parameters
        ----------
        config : VaraConfig | None
            If None, a default config is built from the lattice context
            or a safe empty default.

        Returns
        -------
        dict
            Serialized VaraScanReport.
        """
        from vara_scan import run_vara_scan, VaraConfig

        if config is None:
            config = VaraConfig(
                keywords=["AI", "compute", "GPU", "inference", "LLM"],
                sweep_depth_hours=6,
                active_planes=["tech", "economic", "geopolitical"],
                scan_label=f"vara_auto_{self._scan_count}",
            )

        report        = run_vara_scan(config)
        self.last_scan = report
        self._scan_count += 1
        return asdict(report)

    def status(self) -> dict:
        """Return a lightweight status dict for the operator console."""
        return {
            "vara_version": self.VERSION,
            "scan_count":   self._scan_count,
            "last_scan_ts": getattr(self.last_scan, "timestamp", None),
            "lattice_link": self.lattice is not None,
        }

    def __repr__(self) -> str:
        return f"<Vara v{self.VERSION} scans={self._scan_count}>"
