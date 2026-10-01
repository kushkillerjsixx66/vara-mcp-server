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
