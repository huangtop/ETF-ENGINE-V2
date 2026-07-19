import json
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from etf_engine.repository import SeedRepository, PriceRepository
from etf_engine.services.holding_service import HoldingService, overlap
from etf_engine.settings import settings


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def load_translations() -> dict[str, dict]:
    """Support either [{etf_id, name_zh}] or {etf_id: name_zh/dict} formats."""
    path = settings.seed_dir / "translations_zh.json"

    if not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    result = {}

    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict) or not row.get("etf_id"):
                continue
            result[row["etf_id"]] = {
                "name_zh": row.get("name_zh"),
                "short_name_zh": row.get("short_name_zh"),
            }
    elif isinstance(raw, dict):
        for etf_id, value in raw.items():
            if isinstance(value, str):
                result[etf_id] = {"name_zh": value}
            elif isinstance(value, dict):
                result[etf_id] = {
                    "name_zh": value.get("name_zh"),
                    "short_name_zh": value.get("short_name_zh"),
                }

    return result


def build_public() -> None:
    repo = SeedRepository()
    entities = [x.model_dump() for x in repo.entities()]
    classifications = [x.model_dump() for x in repo.classifications()]
    translations = load_translations()

    metrics_path = settings.normalized_dir / "metrics" / "latest.json"
    metrics = (
        json.loads(metrics_path.read_text(encoding="utf-8"))
        if metrics_path.exists()
        else []
    )

    metric_map = {}
    for row in metrics:
        metric_map.setdefault(row["etf_id"], {})[row["metric_code"]] = {
            "value": row["value"],
            "unit": row.get("unit", "ratio"),
        }

    class_map = {}
    for row in classifications:
        class_map.setdefault(row["etf_id"], []).append(
            {
                "dimension": row["dimension"],
                "code": row["code"],
            }
        )

    payload = []
    price_repo = PriceRepository()
    holding_service = HoldingService()
    holdings_map = {}
    reverse_holdings = {}

    for entity in entities:
        etf_id = entity["etf_id"]
        translated = translations.get(etf_id, {})

        # Translation is applied here, rather than overwriting the canonical English name.
        name_zh = translated.get("name_zh")
        short_name_zh = translated.get("short_name_zh")
        display_name = name_zh or entity.get("name") or entity.get("ticker")
        display_short_name = (
            short_name_zh
            or name_zh
            or entity.get("short_name")
            or entity.get("ticker")
        )

        frame = price_repo.load(etf_id)
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
                trend = [
                    {
                        "date": str(date.date()),
                        "value": round(float(value), 2),
                    }
                    for date, value in norm.items()
                ]

        holdings = holding_service.load(etf_id)
        holdings_map[etf_id] = holdings

        for row in holdings:
            reverse_holdings.setdefault(row["holding_symbol"], []).append(
                {
                    "etf_id": etf_id,
                    "ticker": entity["ticker"],
                    "name": display_name,
                    "name_en": entity.get("name"),
                    "weight": row["weight"],
                }
            )

        holding_summary = {
            "holding_count": len(holdings),
            "top_10_weight": round(
                sum(float(x["weight"]) for x in holdings[:10]),
                6,
            ),
            "top_3_weight": round(
                sum(float(x["weight"]) for x in holdings[:3]),
                6,
            ),
        }

        item = {
            **entity,
            "name_en": entity.get("name"),
            "short_name_en": entity.get("short_name"),
            "name_zh": name_zh,
            "short_name_zh": short_name_zh,
            "display_name": display_name,
            "display_short_name": display_short_name,
            "classifications": class_map.get(etf_id, []),
            "metrics": metric_map.get(etf_id, {}),
            "latest_price": latest_price,
            "trend": trend,
            "top_holdings": holdings[:20],
            "holdings_summary": holding_summary,
        }

        payload.append(item)
        write_json(settings.public_dir / "etf" / f"{etf_id}.json", item)

    for symbol, rows in reverse_holdings.items():
        rows.sort(key=lambda x: x["weight"], reverse=True)
        write_json(settings.public_dir / "holdings" / f"{symbol}.json", rows)

    write_json(settings.public_dir / "holdings_index.json", reverse_holdings)

    ai_ids = {
        row["etf_id"]
        for row in classifications
        if row["dimension"] == "theme"
        and row["code"] == "artificial_intelligence"
    }

    overlap_index = []

    for left_id, right_id in combinations(sorted(ai_ids), 2):
        left = holdings_map.get(left_id, [])
        right = holdings_map.get(right_id, [])

        if not left or not right:
            continue

        result = overlap(left, right)
        row = {
            "left_etf_id": left_id,
            "right_etf_id": right_id,
            **result,
        }

        overlap_index.append(
            {key: value for key, value in row.items() if key != "shared_holdings"}
        )

        write_json(
            settings.public_dir / "overlap" / f"{left_id}__{right_id}.json",
            row,
        )

    write_json(settings.public_dir / "overlap_index.json", overlap_index)

    generated = datetime.now(timezone.utc).isoformat()

    write_json(settings.public_dir / "etfs.json", payload)
    write_json(settings.public_dir / "classifications.json", classifications)
    write_json(settings.public_dir / "latest_metrics.json", metrics)

    for market in ("TW", "US"):
        write_json(
            settings.public_dir / "markets" / f"{market}.json",
            [
                item
                for item in payload
                if item["listing_market"] == market
            ],
        )

    write_json(
        settings.public_dir / "manifest.json",
        {
            "schema_version": "2.2",
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


if __name__ == "__main__":
    build_public()