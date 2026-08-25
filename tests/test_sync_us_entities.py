from etf_engine.services.sync_us_entities import candidate_scope, parse_symbol_directory


def test_parse_nasdaq_directory_keeps_real_etfs_only():
    text = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
        "AAA|Alpha ETF|G|N|N|100|Y|N\n"
        "BBB|Beta Inc|Q|N|N|100|N|N\n"
        "TEST|Test ETF|Q|Y|N|100|Y|N\n"
        "File Creation Time: 2026082518|||||||\n"
    )
    assert parse_symbol_directory(text, nasdaq=True) == [
        {"ticker": "AAA", "name": "Alpha ETF", "listing_exchange": "Nasdaq"}
    ]


def test_parse_other_directory_maps_exchange():
    text = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "LYTE|Roundhill Photonics & Optics ETF|Z|LYTE|Y|100|N|LYTE\n"
    )
    assert parse_symbol_directory(text, nasdaq=False)[0]["listing_exchange"] == "Cboe BZX"


def test_candidate_scope_only_auto_enrolls_relevant_non_tactical_funds():
    assert candidate_scope("Roundhill Photonics & Optics ETF") == "ai_technology"
    assert candidate_scope("Example S&P 500 ETF") == "broad_market"
    assert candidate_scope("Example Municipal Bond ETF") is None
    assert candidate_scope("Example Daily 2X Semiconductor ETF") is None
