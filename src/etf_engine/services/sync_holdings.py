from __future__ import annotations

import argparse
import json

from etf_engine.repository import SeedRepository
from etf_engine.services.holding_service import HoldingService
from etf_engine.services.holdings_change_export import HoldingsChangeExporter


def sync(market: str = "all", active_only: bool = True) -> dict:
    entities = SeedRepository().entities()
    service = HoldingService()
    synced = 0
    cached = 0
    failed = 0

    for entity in entities:
        if active_only and not entity.active:
            continue
        if market != "all" and entity.listing_market != market:
            continue
        result = service.sync_with_status(entity)
        if result.fetched:
            synced += 1
        elif result.rows:
            cached += 1
        else:
            failed += 1

    result = {
        "synced": synced,
        "cached": cached,
        "synced_or_cached": synced + cached,
        "failed": failed,
        "market": market,
    }
    HoldingsChangeExporter().build()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", default="all", choices=("all", "TW", "US"))
    args = parser.parse_args()
    print(json.dumps(sync(args.market), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
