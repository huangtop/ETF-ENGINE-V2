from __future__ import annotations

import argparse
import json
from pathlib import Path

from etf_engine.providers.official_openapi import fetch_official_tw_entities
from etf_engine.settings import settings


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def sync(
    output: Path | None = None,
    minimum_tw_count: int = 200,
    allow_current_us_fallback: bool = True,
) -> dict:
    output = output or settings.seed_dir / "entities.json"
    current = read_json(output, [])
    official = fetch_official_tw_entities()

    overrides = {
        row["ticker"]: row
        for row in read_json(settings.seed_dir / "tw_entity_overrides.json", [])
    }
    us_path = settings.seed_dir / "entities_us.json"
    us = read_json(us_path, [])
    if not us and allow_current_us_fallback:
        us = [row for row in current if row.get("listing_market") == "US"]

    merged: list[dict] = []
    for row in official:
        override = overrides.get(row["ticker"], {})
        for key in (
            "short_name",
            "benchmark_symbol",
            "benchmark_name",
            "issuer",
            "include_in_ranking",
            "notes",
        ):
            if key in override:
                row[key] = override[key]
        merged.append(row)

    tickers = {row["ticker"] for row in merged}
    if "0050" not in tickers:
        raise RuntimeError("Official universe validation failed: 0050 missing")
    if len(merged) < minimum_tw_count:
        raise RuntimeError(
            f"Official universe validation failed: only {len(merged)} TW ETFs"
        )
    if not us:
        raise RuntimeError(
            "US seed is empty. Add data/seed/entities_us.json or keep US rows "
            "in data/seed/entities.json."
        )

    all_rows = sorted(
        [*merged, *us],
        key=lambda row: (row["listing_market"], row["ticker"]),
    )
    write_json(output, all_rows)
    return {
        "tw": len(merged),
        "us": len(us),
        "total": len(all_rows),
        "contains_0050": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=settings.seed_dir / "entities.json",
    )
    parser.add_argument("--minimum-tw-count", type=int, default=200)
    args = parser.parse_args()
    print(
        json.dumps(
            sync(args.output, args.minimum_tw_count),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
