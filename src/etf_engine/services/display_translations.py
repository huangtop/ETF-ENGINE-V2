from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from etf_engine.settings import settings


def load_holding_translations(path: Path | None = None) -> dict[str, dict[str, Any]]:
    source = path or settings.seed_dir / "holding_translations_zh.json"
    if not source.exists():
        return {}
    rows = json.loads(source.read_text(encoding="utf-8"))
    return {
        str(row["holding_symbol"]).strip().upper(): row
        for row in rows
        if isinstance(row, dict) and row.get("holding_symbol")
    }


def localize_holding(
    row: dict[str, Any], translations: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    symbol = str(row["holding_symbol"]).strip().upper()
    translation = translations.get(symbol, {})
    name_en = row.get("holding_name") or translation.get("name_en")
    name_zh = translation.get("name_zh")
    display_name = name_zh or name_en or symbol
    bilingual_name = f"{name_en}（{name_zh}）" if name_en and name_zh else display_name
    return {
        **row,
        "holding_name_en": name_en,
        "holding_name_zh": name_zh,
        "display_name": display_name,
        "display_label": f"({symbol}){display_name}",
        "bilingual_name": bilingual_name,
    }
