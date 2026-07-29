import json

from etf_engine.repository import SeedRepository
from etf_engine.services.display_translations import (
    load_holding_translations,
    localize_holding,
)
from etf_engine.services.public_builder import load_translations


def test_localizes_holding_without_changing_canonical_name(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text(
        json.dumps(
            [
                {
                    "holding_symbol": "TSLA",
                    "name_en": "Tesla Inc",
                    "name_zh": "特斯拉",
                    "source": "manual",
                }
            ]
        ),
        encoding="utf-8",
    )
    translations = load_holding_translations(path)
    localized = localize_holding(
        {
            "holding_symbol": "TSLA",
            "holding_name": "Tesla Inc",
            "weight": 0.1,
        },
        translations,
    )

    assert localized["holding_name"] == "Tesla Inc"
    assert localized["holding_name_en"] == "Tesla Inc"
    assert localized["holding_name_zh"] == "特斯拉"
    assert localized["display_name"] == "特斯拉"
    assert localized["display_label"] == "(TSLA)特斯拉"
    assert localized["bilingual_name"] == "Tesla Inc（特斯拉）"


def test_unknown_holding_falls_back_to_provider_english():
    localized = localize_holding(
        {
            "holding_symbol": "UNKNOWN",
            "holding_name": "Unknown Company Inc",
            "weight": 0.1,
        },
        {},
    )

    assert localized["holding_name_zh"] is None
    assert localized["display_name"] == "Unknown Company Inc"
    assert localized["display_label"] == "(UNKNOWN)Unknown Company Inc"


def test_iqmm_uses_reviewed_taiwan_name():
    translations = load_holding_translations()
    localized = localize_holding(
        {
            "holding_symbol": "IQMM",
            "holding_name": "ProShares GENIUS Money Market ETF",
            "weight": 0.5,
        },
        translations,
    )

    assert localized["display_label"] == "(IQMM)ProShares GENIUS貨幣市場主動型ETF"


def test_all_active_us_etfs_have_taiwan_display_name():
    translations = load_translations()
    active_us = [
        entity
        for entity in SeedRepository().entities()
        if entity.active and entity.listing_market == "US"
    ]

    assert active_us
    assert all(translations.get(entity.etf_id, {}).get("name_zh") for entity in active_us)
