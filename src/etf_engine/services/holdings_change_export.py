from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from etf_engine.services.display_translations import load_holding_translations
from etf_engine.services.holdings_history import COVERAGE
from etf_engine.settings import settings


SCHEMA_VERSION = "1.0"
EVENT_TYPES = [
    "ENTERED_TOP_HOLDINGS",
    "EXITED_TOP_HOLDINGS",
    "WEIGHT_INCREASED",
    "WEIGHT_DECREASED",
    "UNCHANGED",
]


class HoldingsChangeExporter:
    """Build deterministic, inference-free public changes from history snapshots."""

    def __init__(
        self,
        history_dir: Path | None = None,
        public_dir: Path | None = None,
        translations_path: Path | None = None,
    ) -> None:
        self.history_dir = history_dir or settings.root / "data" / "history" / "holdings"
        self.public_dir = public_dir or settings.public_dir / "history" / "holdings"
        self.translations = load_holding_translations(translations_path)

    def build(self) -> dict[str, Any]:
        observations_document = self._read(
            self.history_dir / "observations.json",
            {"observations": []},
        )
        history_manifest = self._read(self.history_dir / "manifest.json", {})
        observations_by_etf: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for observation in observations_document.get("observations", []):
            if observation.get("content_changed"):
                observations_by_etf[observation["etf_id"]].append(observation)

        all_latest: list[dict[str, Any]] = []
        total_transitions = 0
        total_events = 0

        for etf_id, observations in sorted(observations_by_etf.items()):
            transitions = []
            previous = None
            for current in observations:
                if previous is not None:
                    transition = self._transition(etf_id, previous, current)
                    transitions.append(transition)
                    total_events += len(transition["changes"])
                previous = current

            if not transitions:
                continue

            total_transitions += len(transitions)
            all_latest.extend(transitions[-1]["changes"])
            self._write_atomic(
                self.public_dir / f"{etf_id}.json",
                {
                    "schema_version": SCHEMA_VERSION,
                    "etf_id": etf_id,
                    "coverage": COVERAGE,
                    "transition_count": len(transitions),
                    "latest_transition": transitions[-1],
                    "transitions": transitions,
                },
            )

        generated_at = history_manifest.get("updated_at")
        latest_document = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "coverage": COVERAGE,
            "selection": "latest_transition_per_etf",
            "changes": all_latest,
        }
        self._write_atomic(self.public_dir / "latest_changes.json", latest_document)

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "history_type": "etf_holdings_changes",
            "generated_at": generated_at,
            "coverage": COVERAGE,
            "event_types": EVENT_TYPES,
            "etf_count": sum(
                1 for observations in observations_by_etf.values() if len(observations) >= 2
            ),
            "transition_count": total_transitions,
            "event_count": total_events,
            "latest_event_count": len(all_latest),
            "latest_changes": "latest_changes.json",
            "etf_history_pattern": "<etf_id>.json",
            "identity_mapping": "not_included",
            "importance_scoring": "not_included",
        }
        self._write_atomic(self.public_dir / "manifest.json", manifest)
        return manifest

    def _transition(
        self,
        etf_id: str,
        previous_observation: dict[str, Any],
        current_observation: dict[str, Any],
    ) -> dict[str, Any]:
        previous_snapshot = self._snapshot(previous_observation["snapshot_id"])
        current_snapshot = self._snapshot(current_observation["snapshot_id"])
        previous = {row["holding_symbol"]: row for row in previous_snapshot["holdings"]}
        current = {row["holding_symbol"]: row for row in current_snapshot["holdings"]}
        changes = [
            self._change(
                etf_id,
                symbol,
                previous.get(symbol),
                current.get(symbol),
                previous_observation,
                current_observation,
            )
            for symbol in sorted(set(previous) | set(current))
        ]
        return {
            "transition_id": current_observation["observation_id"],
            "etf_id": etf_id,
            "coverage": COVERAGE,
            "previous_snapshot_id": previous_observation["snapshot_id"],
            "current_snapshot_id": current_observation["snapshot_id"],
            "previous_observed_at": previous_observation["observed_at"],
            "current_observed_at": current_observation["observed_at"],
            "changes": changes,
        }

    def _change(
        self,
        etf_id: str,
        symbol: str,
        previous: dict[str, Any] | None,
        current: dict[str, Any] | None,
        previous_observation: dict[str, Any],
        current_observation: dict[str, Any],
    ) -> dict[str, Any]:
        previous_weight = float(previous["weight"]) if previous else None
        current_weight = float(current["weight"]) if current else None
        if previous is None:
            change_type = "ENTERED_TOP_HOLDINGS"
        elif current is None:
            change_type = "EXITED_TOP_HOLDINGS"
        elif current_weight > previous_weight:
            change_type = "WEIGHT_INCREASED"
        elif current_weight < previous_weight:
            change_type = "WEIGHT_DECREASED"
        else:
            change_type = "UNCHANGED"

        delta_weight = round((current_weight or 0.0) - (previous_weight or 0.0), 8)
        identity = "|".join(
            [
                etf_id,
                symbol,
                previous_observation["snapshot_id"],
                current_observation["snapshot_id"],
                current_observation["observed_at"],
            ]
        )
        translation = self.translations.get(symbol, {})
        name_en = translation.get("name_en")
        name_zh = translation.get("name_zh")
        display_name = name_zh or name_en or symbol
        bilingual_name = f"{name_en}（{name_zh}）" if name_en and name_zh else display_name
        return {
            "event_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            "etf_id": etf_id,
            "holding_symbol": symbol,
            "holding_name_en": name_en,
            "holding_name_zh": name_zh,
            "holding_display_name": display_name,
            "holding_display_label": f"({symbol}){display_name}",
            "holding_bilingual_name": bilingual_name,
            "previous_weight": previous_weight,
            "current_weight": current_weight,
            "delta_weight": delta_weight,
            "change_type": change_type,
            "previous_source": previous.get("source") if previous else None,
            "current_source": current.get("source") if current else None,
            "previous_snapshot_id": previous_observation["snapshot_id"],
            "current_snapshot_id": current_observation["snapshot_id"],
            "previous_observed_at": previous_observation["observed_at"],
            "current_observed_at": current_observation["observed_at"],
            "coverage": COVERAGE,
        }

    def _snapshot(self, snapshot_id: str) -> dict[str, Any]:
        return self._read(self.history_dir / "snapshots" / f"{snapshot_id}.json", {})

    @staticmethod
    def _read(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_atomic(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
