"""Remove confirmed delisted products from the active ETF entity universe."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed"
REMOVED_IDS = {
    "TW-0059", "TW-0060", "TW-00649", "TW-00659R", "TW-00667",
    "TW-00672L", "TW-00691R", "TW-00698L", "TW-00699R", "TW-00704L",
    "TW-00705R", "TW-00716R", "TW-00729R", "TW-00732", "TW-00774B",
    "TW-00776", "TW-0080", "TW-0081", "TW-008201", "US-IGN",
}


def read(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    for filename in ("entities.json", "classifications.json", "translations_zh.json"):
        path = SEED / filename
        rows = read(path, [])
        write(path, [row for row in rows if row.get("etf_id") not in REMOVED_IDS])

    profiles_path = SEED / "research_profiles.json"
    profile_lines = profiles_path.read_text(encoding="utf-8").splitlines()
    removed_markers = {f'"etf_id":"{etf_id}"' for etf_id in REMOVED_IDS}
    profiles_path.write_text(
        "\n".join(
            line
            for line in profile_lines
            if not any(marker in line for marker in removed_markers)
        )
        + "\n",
        encoding="utf-8",
    )

    retired_path = SEED / "retired_entities.json"
    retired = {row["etf_id"]: row for row in read(retired_path, [])}
    for etf_id in sorted(REMOVED_IDS):
        retired[etf_id] = {
            "etf_id": etf_id,
            "reason": "delisted",
            "removed_from_universe_at": date.today().isoformat(),
        }
    write(retired_path, [retired[key] for key in sorted(retired)])
    print(json.dumps({"removed": len(REMOVED_IDS)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
