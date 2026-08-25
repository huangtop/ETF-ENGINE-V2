import json
from pathlib import Path

from etf_engine.models import ETFEntity


def test_research_profiles_reference_existing_us_universe():
    root = Path(__file__).resolve().parents[1]
    entities = json.loads((root / "data" / "seed" / "entities.json").read_text())
    profiles = json.loads((root / "data" / "seed" / "research_profiles.json").read_text())
    us_ids = {row["etf_id"] for row in entities if row.get("listing_market") == "US"}

    original_ids = {
        "US-AGG",
        "US-AIEQ",
        "US-AIQ",
        "US-ARKK",
        "US-ARKQ",
        "US-ARKX",
        "US-ARTY",
        "US-BAI",
        "US-BITO",
        "US-BND",
        "US-BOTZ",
        "US-BUG",
        "US-CARZ",
        "US-CHAT",
        "US-CHPS",
        "US-CIBR",
        "US-CLOU",
        "US-DGRO",
        "US-DIA",
        "US-DRAM",
        "US-DRIV",
        "US-DTCR",
        "US-FIVG",
        "US-FTXL",
        "US-GLD",
        "US-GRID",
        "US-HACK",
        "US-IDRV",
        "US-IEF",
        "US-IFRA",
        "US-IGPT",
        "US-IGV",
        "US-IHAK",
        "US-IVV",
        "US-IWM",
        "US-JEPI",
        "US-JEPQ",
        "US-KARS",
        "US-MAGS",
        "US-NLR",
        "US-PAVE",
        "US-PSI",
        "US-QQQ",
        "US-QTUM",
        "US-ROBO",
        "US-ROBT",
        "US-SCHD",
        "US-SGOV",
        "US-SHOC",
        "US-SKYY",
        "US-SMH",
        "US-SOXL",
        "US-SOXQ",
        "US-SOXX",
        "US-SPY",
        "US-SRVR",
        "US-THNQ",
        "US-TLT",
        "US-UFO",
        "US-URA",
        "US-URNM",
        "US-USD",
        "US-VEA",
        "US-VIG",
        "US-VNQ",
        "US-VOO",
        "US-VPN",
        "US-VT",
        "US-VTI",
        "US-VWO",
        "US-WCLD",
        "US-WTAI",
        "US-XLE",
        "US-XLF",
        "US-XLK",
        "US-XLV",
        "US-XSD",
    }
    requested_expansion = {
        "US-VXUS", "US-ITOT", "US-QQQM", "US-RSP", "US-VUG", "US-VTV",
        "US-IWF", "US-IWD", "US-SCHG", "US-VO", "US-VB", "US-IJH",
        "US-IJR", "US-IEFA", "US-IEMG", "US-EFA", "US-IXUS", "US-SCHF",
        "US-BNDX", "US-VCIT", "US-VGT", "US-IAU", "US-VYM", "US-SPYM",
        "US-SPLG", "US-SCHX", "US-VV", "US-VEU", "US-VXF", "US-VBR",
        "US-IVW", "US-LYTE",
    }
    assert original_ids <= us_ids
    assert requested_expansion <= us_ids
    assert original_ids <= us_ids
    assert len({row["etf_id"] for row in profiles}) == len(profiles)
    assert {row["etf_id"] for row in profiles} <= us_ids
    assert {row["tier"] for row in profiles} <= {"primary", "context", "tactical"}
    assert all(row.get("nodes") and row.get("roles") for row in profiles)


def test_required_research_control_points_are_defined():
    root = Path(__file__).resolve().parents[1]
    profiles = json.loads((root / "data" / "seed" / "research_profiles.json").read_text())
    by_id = {row["etf_id"]: row for row in profiles}

    assert by_id["US-SPY"]["roles"] == ["sp500_benchmark"]
    assert by_id["US-QQQ"]["roles"] == ["nasdaq100_benchmark"]
    assert by_id["US-IWM"]["roles"] == ["small_cap_benchmark"]
    assert by_id["US-DRAM"]["roles"] == ["memory_specialist"]
    assert by_id["US-QTUM"]["nodes"] == ["quantum_computing"]
    assert by_id["US-SOXL"]["tier"] == "tactical"
    assert by_id["US-USD"]["tier"] == "tactical"


def test_new_products_keep_original_universe_and_lifecycle_metadata():
    root = Path(__file__).resolve().parents[1]
    entities = json.loads((root / "data" / "seed" / "entities.json").read_text())
    by_id = {row["etf_id"]: row for row in entities}
    added = {
        "US-SLV",
        "US-XBI",
        "US-IBB",
        "US-ARKG",
        "US-MUU",
        "US-MUD",
        "US-MULL",
        "US-MUZ",
        "US-SNXX",
        "US-SNDQ",
    }

    assert added <= set(by_id)
    assert all(by_id[etf_id]["active"] for etf_id in added)
    assert all(by_id[etf_id]["product_status"] == "active" for etf_id in added)
    assert by_id["US-MUZ"]["inception_date"] == "2026-06-09"
    assert by_id["US-SLV"]["inception_date"] == "2006-04-21"
    assert by_id["US-XBI"]["inception_date"] == "2006-01-31"
    assert by_id["US-IBB"]["inception_date"] == "2001-02-05"
    assert by_id["US-AGG"].get("inception_date") is None
    assert by_id["US-AIQ"].get("inception_date") is None
    assert by_id["US-ARTY"].get("inception_date") is None


def test_lifecycle_dates_serialize_as_iso_json_values():
    entity = ETFEntity.model_validate(
        {
            "etf_id": "US-MUZ",
            "ticker": "MUZ",
            "quote_symbol": "MUZ",
            "name": "MUZ",
            "listing_market": "US",
            "listing_exchange": "US",
            "currency": "USD",
            "benchmark_symbol": "MU",
            "inception_date": "2026-06-09",
        }
    )

    assert entity.model_dump(mode="json")["inception_date"] == "2026-06-09"
