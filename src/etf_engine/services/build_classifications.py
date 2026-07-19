from __future__ import annotations

import argparse
import json
from pathlib import Path

from etf_engine.settings import settings


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def add(rows, seen, etf_id, dimension, code, source="taxonomy_v2.5"):
    key = (etf_id, dimension, code)
    if key in seen:
        return
    rows.append(
        {
            "etf_id": etf_id,
            "dimension": dimension,
            "code": code,
            "source": source,
        }
    )
    seen.add(key)


def contains(text: str, *terms: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def classify_entity(entity: dict, rows: list, seen: set) -> None:
    etf_id = entity["etf_id"]
    ticker = entity["ticker"]
    name = entity.get("name", "")
    benchmark = entity.get("benchmark_name") or ""
    text = f" {ticker} {name} {benchmark} ".lower()

    add(rows, seen, etf_id, "listing_market", entity["listing_market"].lower())
    add(
        rows,
        seen,
        etf_id,
        "management_style",
        entity.get("management_style", "passive"),
    )
    add(
        rows,
        seen,
        etf_id,
        "product_structure",
        entity.get("product_structure", "standard"),
    )
    add(
        rows,
        seen,
        etf_id,
        "asset_class",
        entity.get("asset_class") or "equity",
    )

    if entity["listing_market"] == "TW":
        if contains(text, "美國", "s&p", "nasdaq", "道瓊", "費城", "fang"):
            geography = "united_states"
        elif contains(text, "全球", "world", "global"):
            geography = "global"
        elif contains(text, "中國", "陸股", "上證", "滬深", "恒生", "中概"):
            geography = "greater_china"
        elif contains(text, "日本", "日經", "topix"):
            geography = "japan"
        elif contains(text, "印度", "nifty"):
            geography = "india"
        else:
            geography = "taiwan"
    else:
        if ticker == "VT":
            geography = "global"
        elif ticker == "VEA":
            geography = "developed_ex_us"
        elif ticker == "VWO":
            geography = "emerging_markets"
        elif contains(text, "global"):
            geography = "global"
        else:
            geography = "united_states"
    add(rows, seen, etf_id, "geography", geography)

    strategies = {
        "high_dividend": ("高股息", "高息", "優息", "股利精選", "dividend equity"),
        "dividend_growth": ("股息成長", "dividend growth", "dividend appreciation"),
        "income": ("收益", "鑫收", "income", "股息"),
        "covered_call": ("covered call", "equity premium income"),
        "low_volatility": ("低波", "low volatility"),
        "momentum": ("動能", "momentum"),
        "value": ("價值", "value"),
        "growth": ("成長", "增長", "growth"),
        "quality": ("優質", "品質", "quality"),
        "equal_weight": ("等權", "equal weight"),
        "esg": ("esg", "永續", "低碳", "公司治理"),
        "smart_beta": ("smart", "智慧"),
        "treasury": ("公債", "treasury"),
        "investment_grade_bond": ("投資級", "investment grade"),
        "high_yield_bond": ("非投資級", "高收益債", "high yield"),
        "gold": ("黃金", "gold"),
        "oil": ("原油", "oil"),
        "real_estate": ("不動產", "房地產", "reit", "real estate"),
    }
    for code, terms in strategies.items():
        if contains(text, *terms):
            add(rows, seen, etf_id, "strategy", code)

    structure = entity.get("product_structure", "standard")
    if structure != "standard":
        add(rows, seen, etf_id, "strategy", structure)

    if ticker in {"SPY", "VOO", "IVV", "VTI", "VT", "DIA"} or contains(
        text,
        "台灣50",
        "台50",
        "top50",
        "加權",
        "msci台灣",
        "s&p 500",
        "total market",
        "total stock",
        "total world",
        "dow jones industrial",
    ):
        add(rows, seen, etf_id, "strategy", "broad_market")

    themes = {
        "artificial_intelligence": (
            "人工智慧",
            "ai50",
            "ai新經濟",
            "ai優息",
            " artificial intelligence ",
        ),
        "robotics": ("機器人", "robotics", "automation"),
        "semiconductors": ("半導體", "晶圓", "semiconductor"),
        "cloud_computing": ("雲端", "cloud computing"),
        "cybersecurity": ("資安", "cybersecurity"),
        "data_center": ("資料中心", "data center", "digital infrastructure"),
        "electric_vehicles": ("電動車", "未來車", "electric vehicle"),
        "clean_energy": ("綠能", "潔淨能源", "clean energy"),
        "nuclear_energy": ("核能", "鈾礦", "nuclear", "uranium"),
        "space": ("太空", "space"),
        "quantum_computing": ("量子", "quantum"),
        "infrastructure": ("基礎建設", "infrastructure"),
    }
    for code, terms in themes.items():
        if contains(text, *terms):
            add(rows, seen, etf_id, "theme", code)


def build(
    entities_path: Path | None = None,
    curated_path: Path | None = None,
    output_path: Path | None = None,
) -> dict:
    entities_path = entities_path or settings.seed_dir / "entities.json"
    curated_path = (
        curated_path
        or settings.seed_dir / "classifications_curated_us_ai.json"
    )
    output_path = output_path or settings.seed_dir / "classifications.json"

    entities = read_json(entities_path, [])
    curated = read_json(curated_path, [])
    # Preserve current-main curated classifications even when the new optional
    # curated file has not been created yet.
    if not curated and output_path.exists():
        curated = read_json(output_path, [])

    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for entity in entities:
        classify_entity(entity, rows, seen)
    for row in curated:
        add(
            rows,
            seen,
            row["etf_id"],
            row["dimension"],
            row["code"],
            row.get("source", "curated"),
        )

    entity_ids = {row["etf_id"] for row in entities}
    explicit = {
        "TW-0050": [
            ("strategy", "broad_market"),
            ("market_cap", "large_cap"),
            ("portfolio_role", "core_equity"),
        ],
        "TW-00400A": [
            ("strategy", "high_dividend"),
            ("strategy", "momentum"),
        ],
        "US-SCHD": [
            ("strategy", "high_dividend"),
            ("strategy", "quality"),
        ],
        "US-JEPI": [
            ("strategy", "income"),
            ("strategy", "covered_call"),
        ],
        "US-JEPQ": [
            ("strategy", "income"),
            ("strategy", "covered_call"),
        ],
    }
    for etf_id, tags in explicit.items():
        if etf_id not in entity_ids:
            continue
        for dimension, code in tags:
            add(rows, seen, etf_id, dimension, code, "curated_v2.5")

    rows.sort(key=lambda row: (row["etf_id"], row["dimension"], row["code"]))
    write_json(output_path, rows)
    return {
        "entities": len(entities),
        "classifications": len(rows),
        "contains_0050": "TW-0050" in entity_ids,
        "output": str(output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--entities",
        type=Path,
        default=settings.seed_dir / "entities.json",
    )
    parser.add_argument(
        "--curated",
        type=Path,
        default=settings.seed_dir / "classifications_curated_us_ai.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=settings.seed_dir / "classifications.json",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            build(args.entities, args.curated, args.output),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
