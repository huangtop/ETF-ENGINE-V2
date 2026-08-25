"""Record last-known-good holdings caches missing from immutable history."""

from __future__ import annotations

import hashlib
import json

from etf_engine.services.holdings_history import HoldingsHistoryService
from etf_engine.settings import settings


def content_hash(rows: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def main() -> None:
    service = HoldingsHistoryService()
    index_path = service.history_dir / "snapshot_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    reconciled: list[str] = []
    for cache_path in sorted((settings.normalized_dir / "holdings").glob("*.json")):
        holdings = json.loads(cache_path.read_text(encoding="utf-8"))
        if not holdings:
            continue
        etf_id = cache_path.stem
        canonical = service._canonical_content(etf_id, holdings)
        actual = content_hash(canonical)
        current = index.get("etfs", {}).get(etf_id, {}).get("current")
        snapshot_path = service.snapshots_dir / f"{current}.json"
        expected = None
        if current and snapshot_path.exists():
            expected = json.loads(snapshot_path.read_text(encoding="utf-8")).get("content_sha256")
        if actual == expected:
            continue
        service.record(etf_id, holdings, coverage="top_holdings_only")
        reconciled.append(etf_id)
        index = json.loads(index_path.read_text(encoding="utf-8"))
    print(json.dumps({"reconciled": len(reconciled), "etf_ids": reconciled}, ensure_ascii=False))


if __name__ == "__main__":
    main()
