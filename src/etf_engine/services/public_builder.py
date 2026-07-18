import json
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from etf_engine.repository import SeedRepository, PriceRepository
from etf_engine.services.holding_service import HoldingService, overlap
from etf_engine.settings import settings


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def build_public() -> None:
    repo = SeedRepository()
    entities = [x.model_dump() for x in repo.entities()]
    classifications = [x.model_dump() for x in repo.classifications()]
    metrics_path = settings.normalized_dir / "metrics" / "latest.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else []
    metric_map = {}
    for row in metrics:
        # 為每個 ETF 建立指標映射: {metric_code: {value, unit}}
        if row["etf_id"] not in metric_map:
            metric_map[row["etf_id"]] = {}
        metric_map[row["etf_id"]][row["metric_code"]] = {
            "value": row["value"],
            "unit": row.get("unit", "ratio")
        }
    class_map = {}
    for row in classifications:
        class_map.setdefault(row["etf_id"], []).append({"dimension": row["dimension"], "code": row["code"]})

    payload = []
    price_repo = PriceRepository()
    holding_service = HoldingService()
    holdings_map = {}
    reverse_holdings = {}

    for entity in entities:
        frame = price_repo.load(entity["etf_id"])
        latest_price = None
        trend = []
        if not frame.empty:
            series = frame["adj_close"] if "adj_close" in frame else frame["close"]
            series = series.dropna()
            if len(series):
                latest_price = {
                    "date": str(series.index[-1].date()),
                    "value": round(float(series.iloc[-1]), 4),
                    "currency": entity["currency"],
                }
                sample = series.iloc[-756:]
                norm = sample / sample.iloc[0] * 100
                trend = [{"date": str(d.date()), "value": round(float(v), 2)} for d, v in norm.items()]

        holdings = holding_service.load(entity["etf_id"])
        holdings_map[entity["etf_id"]] = holdings
        for row in holdings:
            reverse_holdings.setdefault(row["holding_symbol"], []).append(
                {
                    "etf_id": entity["etf_id"],
                    "ticker": entity["ticker"],
                    "name": entity["name"],
                    "weight": row["weight"],
                }
            )
        holding_summary = {
            "holding_count": len(holdings),
            "top_10_weight": round(sum(float(x["weight"]) for x in holdings[:10]), 6),
            "top_3_weight": round(sum(float(x["weight"]) for x in holdings[:3]), 6),
        }
        item = {
            **entity,
            "classifications": class_map.get(entity["etf_id"], []),
            "metrics": metric_map.get(entity["etf_id"], {}),
            "latest_price": latest_price,
            "trend": trend,
            "top_holdings": holdings[:20],
            "holdings_summary": holding_summary,
        }
        payload.append(item)
        write_json(settings.public_dir / "etf" / f"{entity['etf_id']}.json", item)

    for symbol, rows in reverse_holdings.items():
        rows.sort(key=lambda x: x["weight"], reverse=True)
        write_json(settings.public_dir / "holdings" / f"{symbol}.json", rows)
    write_json(settings.public_dir / "holdings_index.json", reverse_holdings)

    # Precompute overlap only for US AI-themed ETFs to keep artifacts compact.
    ai_ids = {
        row["etf_id"]
        for row in classifications
        if row["dimension"] == "theme" and row["code"] == "artificial_intelligence"
    }
    overlap_index = []
    for left_id, right_id in combinations(sorted(ai_ids), 2):
        left, right = holdings_map.get(left_id, []), holdings_map.get(right_id, [])
        if not left or not right:
            continue
        result = overlap(left, right)
        row = {"left_etf_id": left_id, "right_etf_id": right_id, **result}
        overlap_index.append({k: v for k, v in row.items() if k != "shared_holdings"})
        write_json(settings.public_dir / "overlap" / f"{left_id}__{right_id}.json", row)
    write_json(settings.public_dir / "overlap_index.json", overlap_index)

    generated = datetime.now(timezone.utc).isoformat()
    write_json(settings.public_dir / "etfs.json", payload)
    write_json(settings.public_dir / "classifications.json", classifications)
    write_json(settings.public_dir / "latest_metrics.json", metrics)
    for market in ("TW", "US"):
        write_json(settings.public_dir / "markets" / f"{market}.json", [x for x in payload if x["listing_market"] == market])
    write_json(
        settings.public_dir / "manifest.json",
        {
            "schema_version": "2.1",
            "generated_at": generated,
            "etf_count": len(payload),
            "holding_symbols": len(reverse_holdings),
            "overlap_pairs": len(overlap_index),
            "markets": {
                "TW": sum(x["listing_market"] == "TW" for x in payload),
                "US": sum(x["listing_market"] == "US" for x in payload),
            },
        },
    )
