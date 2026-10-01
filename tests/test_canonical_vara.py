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
