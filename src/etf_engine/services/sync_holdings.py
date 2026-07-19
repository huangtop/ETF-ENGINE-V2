from __future__ import annotations

import argparse
import json

from etf_engine.repository import SeedRepository
from etf_engine.services.holding_service import HoldingService


def sync(market: str = "all", active_only: bool = True) -> dict:
    entities = SeedRepository().entities()
    service = HoldingService()
    synced_or_cached = 0
    failed = 0

    for entity in entities:
        if active_only and not entity.active:
            continue
        if market != "all" and entity.listing_market != market:
            continue
        rows = service.sync(entity)
        if rows:
            synced_or_cached += 1
        else:
            failed += 1

    return {
        "synced_or_cached": synced_or_cached,
        "failed": failed,
        "market": market,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--market", default="all", choices=("all", "TW", "US")
    )
    args = parser.parse_args()
    print(json.dumps(sync(args.market), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
