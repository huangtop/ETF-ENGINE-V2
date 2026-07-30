import json
from pathlib import Path


def test_research_profiles_reference_existing_us_universe():
    root = Path(__file__).resolve().parents[1]
    entities = json.loads((root / "data" / "seed" / "entities.json").read_text())
    profiles = json.loads(
        (root / "data" / "seed" / "research_profiles.json").read_text()
    )
    us_ids = {
        row["etf_id"] for row in entities if row.get("listing_market") == "US"
    }

    assert len(us_ids) == 78
    assert len({row["etf_id"] for row in profiles}) == len(profiles)
    assert {row["etf_id"] for row in profiles} <= us_ids
    assert {row["tier"] for row in profiles} <= {"primary", "context", "tactical"}
    assert all(row.get("nodes") and row.get("roles") for row in profiles)


def test_required_research_control_points_are_defined():
    root = Path(__file__).resolve().parents[1]
    profiles = json.loads(
        (root / "data" / "seed" / "research_profiles.json").read_text()
    )
    by_id = {row["etf_id"]: row for row in profiles}

    assert by_id["US-SPY"]["roles"] == ["sp500_benchmark"]
    assert by_id["US-QQQ"]["roles"] == ["nasdaq100_benchmark"]
    assert by_id["US-IWM"]["roles"] == ["small_cap_benchmark"]
    assert by_id["US-DRAM"]["roles"] == ["memory_specialist"]
    assert by_id["US-QTUM"]["nodes"] == ["quantum_computing"]
    assert by_id["US-SOXL"]["tier"] == "tactical"
    assert by_id["US-USD"]["tier"] == "tactical"
