import json
from datetime import datetime, timezone

from etf_engine.services.holdings_change_export import HoldingsChangeExporter
from etf_engine.services.holdings_history import HoldingsHistoryService


def clock(*values):
    iterator = iter(values)
    return lambda: next(iterator)


def rows(**weights):
    return [
        {
            "etf_id": "US-QQQ",
            "holding_symbol": symbol,
            "weight": weight,
            "source": "yahoo",
            "as_of": None,
        }
        for symbol, weight in weights.items()
    ]


def test_exports_all_raw_change_types(tmp_path):
    history_dir = tmp_path / "history"
    public_dir = tmp_path / "public"
    history = HoldingsHistoryService(
        history_dir,
        clock(
            datetime(2026, 7, 29, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 30, 1, tzinfo=timezone.utc),
        ),
    )
    history.record("US-QQQ", rows(MU=0.005, NVDA=0.082, MSFT=0.071, AMD=0.03))
    history.record("US-QQQ", rows(AVGO=0.02, NVDA=0.09, MSFT=0.071, AMD=0.02))

    manifest = HoldingsChangeExporter(history_dir, public_dir).build()
    latest = json.loads((public_dir / "latest_changes.json").read_text())
    etf_history = json.loads((public_dir / "US-QQQ.json").read_text())
    changes = {row["holding_symbol"]: row for row in latest["changes"]}

    assert changes["AVGO"]["change_type"] == "ENTERED_TOP_HOLDINGS"
    assert changes["MU"]["change_type"] == "EXITED_TOP_HOLDINGS"
    assert changes["NVDA"]["change_type"] == "WEIGHT_INCREASED"
    assert changes["NVDA"]["holding_name_zh"] == "輝達"
    assert changes["NVDA"]["holding_display_label"] == "(NVDA)輝達"
    assert changes["AMD"]["change_type"] == "WEIGHT_DECREASED"
    assert changes["MSFT"]["change_type"] == "UNCHANGED"
    assert changes["MU"]["previous_weight"] == 0.005
    assert changes["MU"]["current_weight"] is None
    assert changes["MU"]["previous_observed_at"] == "2026-07-29T01:00:00Z"
    assert changes["MU"]["current_observed_at"] == "2026-07-30T01:00:00Z"
    assert len(changes["MU"]["event_id"]) == 64
    assert etf_history["transition_count"] == 1
    assert manifest["event_count"] == 5
    assert manifest["identity_mapping"] == "not_included"


def test_same_content_does_not_create_duplicate_transition(tmp_path):
    history_dir = tmp_path / "history"
    public_dir = tmp_path / "public"
    history = HoldingsHistoryService(
        history_dir,
        clock(
            datetime(2026, 7, 29, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 30, 1, tzinfo=timezone.utc),
        ),
    )
    holdings = rows(NVDA=0.082)
    history.record("US-QQQ", holdings)
    history.record("US-QQQ", holdings)

    manifest = HoldingsChangeExporter(history_dir, public_dir).build()

    assert manifest["transition_count"] == 0
    assert json.loads((public_dir / "latest_changes.json").read_text())["changes"] == []
    assert not (public_dir / "US-QQQ.json").exists()


def test_reverting_to_prior_content_exports_a_new_transition(tmp_path):
    history_dir = tmp_path / "history"
    public_dir = tmp_path / "public"
    history = HoldingsHistoryService(
        history_dir,
        clock(
            datetime(2026, 7, 29, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 30, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 31, 1, tzinfo=timezone.utc),
        ),
    )
    original = rows(NVDA=0.08)
    history.record("US-QQQ", original)
    history.record("US-QQQ", rows(NVDA=0.09))
    history.record("US-QQQ", original)

    HoldingsChangeExporter(history_dir, public_dir).build()
    document = json.loads((public_dir / "US-QQQ.json").read_text())

    assert document["transition_count"] == 2
    assert document["transitions"][1]["changes"][0]["change_type"] == "WEIGHT_DECREASED"
    assert document["transitions"][1]["current_observed_at"] == "2026-07-31T01:00:00Z"
