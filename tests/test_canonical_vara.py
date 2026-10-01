from src.canonical_vara import (
    CanonicalVaraIntegrity,
    CanonicalVaraPromoter,
    project_operational_report,
)


def test_missing_lineage_is_not_canonical():
    result, _ = project_operational_report(
        {"signals": [{"signal_id": "s1", "content": "x"}]},
        None,
    )
    valid, errors = CanonicalVaraIntegrity().validate(result)

    assert valid is False
    assert any("lineage" in error for error in errors)
    assert CanonicalVaraPromoter().should_promote(result) is False


def test_valid_lineage_allows_deterministic_promotion():
    result, _ = project_operational_report(
        {"signals": [{"signal_id": "s1", "content": "x"}]},
        [{"seq": "001", "operator_id": "JRM-01", "role": "operator", "altitude": "A2"}],
    )
    valid, errors = CanonicalVaraIntegrity().validate(result)

    assert valid is True
    assert errors == []
    assert CanonicalVaraPromoter().should_promote(result) is True


def test_lineage_is_preserved_exactly():
    lineage = [{"seq": "7", "operator_id": "JRM-01", "role": "operator", "altitude": "A2", "extra": "preserve"}]
    result, _ = project_operational_report({"signals": []}, lineage)

    assert result.lineage == lineage


def test_governance_emits_canonical_pipeline_event_without_local_persistence():
    from src.canonical_vara import govern_operational_report

    result = govern_operational_report(
        {"signals": [{"signal_id": "s1", "content": "x"}]},
        [{"seq": "002", "operator_id": "JRM-01", "role": "operator", "altitude": "A2"}],
    )

    conformance = result["canonical_conformance"]
    assert conformance["promotion_allowed"] is True
    event = conformance["promotion_event"]
    assert event["type"] == "vault_promotion"
    assert event["source"] == "vara_scan_pipeline"
    assert event["dispatch"] == "canonical_vault_pipeline_required"
    assert "promotion_path" not in conformance


def test_integrity_matches_canonical_anomaly_contract():
    from src.canonical_vara import CanonicalVaraScanResult

    scan = CanonicalVaraScanResult(
        weak_signals=[],
        trends=[],
        anomalies=[{"field": "novelty", "reason": "drift"}],
        unspecified=[],
        lineage=[{"seq": "003", "operator_id": "JRM-01", "role": "operator", "altitude": "A2"}],
    )

    valid, errors = CanonicalVaraIntegrity().validate(scan)
    assert valid is False
    assert any("field/value/reason" in error for error in errors)


def test_operational_planes_map_to_canonical_domains():
    from src.canonical_vara import canonical_domains_for_plane, project_operational_report

    assert canonical_domains_for_plane("tech") == ("ECON", "INDUSTRIAL")
    assert canonical_domains_for_plane("geopolitical") == ("GEOPOL", "WORLDPOL")
    assert canonical_domains_for_plane("dark") == ("CRYPTO",)
    assert canonical_domains_for_plane("unknown") == ("ECON",)

    result, _ = project_operational_report(
        {"signals": [{"signal_id": "s1", "content": "x", "plane": "geopolitical"}]},
        [{"seq": "004", "operator_id": "JRM-01", "role": "operator", "altitude": "A2"}],
    )
    assert result.weak_signals[0]["canonical_domains"] == ["GEOPOL", "WORLDPOL"]



def test_supervisor_adapter_derives_canonical_lineage_and_event():
    from src.canonical_vara import CanonicalVaraSupervisorAdapter

    adapter = CanonicalVaraSupervisorAdapter()
    context = adapter.build_context(
        {"operator_id": "JRM-01", "role": "operator"},
        {"altitude": "A2", "state": "ACTIVE"},
    )

    assert context["identity"]["operator_id"] == "JRM-01"
    assert context["runtime"]["altitude"] == "A2"
    assert context["lineage"] == [
        {"seq": 1, "operator_id": "JRM-01", "role": "operator", "altitude": "A2"}
    ]

    event = adapter.emit(context)
    assert event["type"] == "epistemic_state"
    assert event["source"] == "vara"
    assert event["payload"] == context


def test_supervisor_adapter_does_not_replace_canonical_authority():
    from src.canonical_vara import CanonicalVaraSupervisorAdapter

    assert "Vault" in (CanonicalVaraSupervisorAdapter.__doc__ or "")



def test_operational_scan_cannot_call_independent_vault_writer():
    from pathlib import Path
    source = Path("vendor/vara/vara_scan.py").read_text(encoding="utf-8")
    assert "route_signals(" not in source
    assert "commit_to_vault(" not in source


def test_veil_vendor_has_no_vault_commit_function():
    from pathlib import Path
    source = Path("vendor/vara/vara_veil_vault.py").read_text(encoding="utf-8")
    assert "def commit_to_vault" not in source
    assert "def route_signals" not in source


def test_canonical_veil_boundary_requires_sovereign_identity_and_altitude():
    from src.canonical_veil import CanonicalVeilBoundaryAdapter

    adapter = CanonicalVeilBoundaryAdapter()
    valid, errors = adapter.validate(
        {"operator_id": "JRM-01", "role": "operator"},
        {"state": "ACTIVE"},
    )

    assert valid is False
    assert "identity missing: sovereignty" in errors
    assert "runtime_state missing: altitude" in errors


def test_canonical_veil_boundary_emits_runtime_then_epistemic_events():
    from src.canonical_veil import CanonicalVeilBoundaryAdapter

    events = CanonicalVeilBoundaryAdapter().events(
        {"operator_id": "JRM-01", "role": "operator", "sovereignty": "operator"},
        {"altitude": "A2", "state": "ACTIVE"},
    )

    assert [event["type"] for event in events] == ["runtime_state", "epistemic_state"]
    assert events[0]["source"] == "veil"
    assert events[1]["source"] == "vara"
    assert events[1]["payload"]["lineage"][0]["altitude"] == "A2"


def test_operational_scan_marks_output_as_unbound_until_canonical_promotion():
    from pathlib import Path

    source = Path("vendor/vara/vara_scan.py").read_text(encoding="utf-8")
    assert '"vault_bound": 0' in source
    assert '"promotion_authority": "canonical_vault_pipeline"' in source
    assert '"veil_authority": "canonical_veil"' in source
