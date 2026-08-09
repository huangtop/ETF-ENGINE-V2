import json
import hashlib
from pathlib import Path

import pytest

from etf_engine.services.release_guard import promote_candidate, validate_candidate


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def item(etf_id="US-SPY"):
    market = etf_id.split("-", 1)[0]
    return {
        "etf_id": etf_id,
        "listing_market": market,
        "name_zh": "標普500 ETF",
        "metrics": {"total_return_1y": {"value": 12.3, "unit": "percent"}},
        "latest_price": {"date": "2026-07-29", "value": 100, "currency": "USD"},
        "trend": [{"date": "2026-07-29", "value": 100}],
        "top_holdings": [
            {
                "holding_symbol": "NVDA",
                "holding_name_zh": "輝達",
                "weight": 0.08,
            }
        ],
    }


def dataset(root: Path, rows):
    write_json(root / "etfs.json", rows)
    for row in rows:
        write_json(root / "etf" / f"{row['etf_id']}.json", row)
    for market in ("TW", "US"):
        write_json(
            root / "markets" / f"{market}.json",
            [row for row in rows if row["listing_market"] == market],
        )
    write_json(root / "classifications.json", [])
    write_json(
        root / "latest_metrics.json",
        [
            {
                "etf_id": row["etf_id"],
                "metric_code": code,
                "value": metric["value"],
                "unit": metric["unit"],
            }
            for row in rows
            for code, metric in row["metrics"].items()
        ],
    )
    write_json(
        root / "manifest.json",
        {
            "etf_count": len(rows),
            "markets": {
                market: sum(row["listing_market"] == market for row in rows)
                for market in ("TW", "US")
            },
        },
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda row: row["metrics"].clear(), "lost metric"),
        (lambda row: row.update(latest_price=None), "lost latest price"),
        (lambda row: row["trend"].clear(), "lost trend"),
        (lambda row: row["top_holdings"].clear(), "holdings became empty"),
        (lambda row: row.update(name_zh=None), "ETF translation disappeared"),
        (
            lambda row: row["top_holdings"][0].update(holding_name_zh=None),
            "holding translation disappeared",
        ),
        (lambda row: row.update(name_zh="錯誤譯名"), "existing ETF translation changed"),
        (
            lambda row: row["top_holdings"][0].update(holding_name_zh="錯誤譯名"),
            "existing holding translation changed",
        ),
        (
            lambda row: (
                row["top_holdings"][0].update(as_of=None),
                row["latest_price"].update(date="2026-07-28"),
            ),
            "latest price date moved backward",
        ),
    ],
)
def test_rejects_last_known_good_regressions(tmp_path, mutation, message):
    baseline = tmp_path / "public"
    candidate = tmp_path / "candidate"
    dataset(baseline, [item()])
    changed = item()
    mutation(changed)
    dataset(candidate, [changed])

    validation = validate_candidate(baseline, candidate)

    assert not validation.passed
    assert any(message in error for error in validation.errors)


def test_rejects_cross_file_inconsistency(tmp_path):
    baseline = tmp_path / "public"
    candidate = tmp_path / "candidate"
    dataset(baseline, [item()])
    dataset(candidate, [item()])
    write_json(candidate / "latest_metrics.json", [])

    validation = validate_candidate(baseline, candidate)

    assert not validation.passed
    assert "latest_metrics.json does not match ETF metrics" in validation.errors


def test_unchanged_holding_cannot_lose_provider_date(tmp_path):
    baseline = tmp_path / "public"
    candidate = tmp_path / "candidate"
    previous = item()
    previous["top_holdings"][0]["as_of"] = "2026-07-19"
    current = item()
    current["top_holdings"][0]["as_of"] = None
    dataset(baseline, [previous])
    dataset(candidate, [current])

    validation = validate_candidate(baseline, candidate)

    assert not validation.passed
    assert any("lost provider as_of" in error for error in validation.errors)


def test_one_year_return_can_be_corrected_to_since_inception(tmp_path):
    baseline = tmp_path / "public"
    candidate = tmp_path / "candidate"
    previous = item()
    previous["metrics"].update(
        {
            "annualized_return": {"value": 12.3, "unit": "percent"},
            "sharpe_ratio": {"value": 0.8, "unit": "ratio"},
        }
    )
    current = item()
    current["metrics"] = {
        "total_return_since_inception": {"value": 3.2, "unit": "percent"},
        "data_years": {"value": 0.4, "unit": "years"},
    }
    dataset(baseline, [previous])
    dataset(candidate, [current])

    validation = validate_candidate(baseline, candidate)

    assert validation.passed


def test_since_inception_does_not_hide_full_year_metric_loss(tmp_path):
    baseline = tmp_path / "public"
    candidate = tmp_path / "candidate"
    previous = item()
    previous["metrics"]["annualized_return"] = {
        "value": 12.3,
        "unit": "percent",
    }
    current = item()
    current["metrics"] = {
        "total_return_since_inception": {"value": 3.2, "unit": "percent"},
        "data_years": {"value": 1.2, "unit": "years"},
    }
    dataset(baseline, [previous])
    dataset(candidate, [current])

    validation = validate_candidate(baseline, candidate)

    assert not validation.passed
    assert any("lost metric annualized_return" in error for error in validation.errors)


def test_valid_candidate_can_replace_baseline(tmp_path):
    public = tmp_path / "public"
    candidate = tmp_path / "candidate"
    previous = item()
    current = item()
    current["latest_price"]["value"] = 101
    dataset(public, [previous])
    dataset(candidate, [current])
    validation = validate_candidate(public, candidate)
    assert validation.passed

    promote_candidate(public, candidate)

    assert json.loads((public / "etfs.json").read_text())[0]["latest_price"]["value"] == 101
    assert not candidate.exists()


def test_failed_promotion_restores_baseline(tmp_path, monkeypatch):
    public = tmp_path / "public"
    candidate = tmp_path / "candidate"
    dataset(public, [item()])
    dataset(candidate, [item("US-QQQ")])
    from etf_engine.services import release_guard

    real_replace = release_guard.os.replace
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("promotion failed")
        return real_replace(source, target)

    monkeypatch.setattr(release_guard.os, "replace", fail_second_replace)

    with pytest.raises(OSError, match="promotion failed"):
        promote_candidate(public, candidate)

    assert json.loads((public / "etfs.json").read_text())[0]["etf_id"] == "US-SPY"


def test_rejects_holdings_cache_that_disagrees_with_history(tmp_path):
    public = tmp_path / "public"
    candidate = tmp_path / "candidate"
    history = tmp_path / "history"
    dataset(public, [item()])
    changed = item()
    changed["top_holdings"][0]["weight"] = 0.09
    dataset(candidate, [changed])
    content = [
        {
            "etf_id": "US-SPY",
            "holding_symbol": "NVDA",
            "weight": 0.08,
            "source": "unknown",
        }
    ]
    expected_hash = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    write_json(
        history / "snapshot_index.json",
        {"etfs": {"US-SPY": {"current": "snapshot-1"}}},
    )
    write_json(
        history / "snapshots" / "snapshot-1.json",
        {"content_sha256": expected_hash},
    )

    validation = validate_candidate(public, candidate, history)

    assert not validation.passed
    assert any("does not match history" in error for error in validation.errors)


def test_accepts_public_top_holdings_subset_of_full_portfolio_snapshot(tmp_path):
    public = tmp_path / "public"
    candidate = tmp_path / "candidate"
    history = tmp_path / "history"
    dataset(public, [item()])
    changed = item()
    changed["top_holdings"][0]["weight"] = 0.09
    dataset(candidate, [changed])
    full_holdings = [
        {
            "etf_id": "US-SPY",
            "holding_symbol": "NVDA",
            "weight": 0.09,
            "source": "unknown",
        },
        {
            "etf_id": "US-SPY",
            "holding_symbol": "MSFT",
            "weight": 0.07,
            "source": "unknown",
        },
    ]
    expected_hash = hashlib.sha256(
        json.dumps(full_holdings, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    write_json(history / "snapshot_index.json", {"etfs": {"US-SPY": {"current": "full"}}})
    write_json(
        history / "snapshots" / "full.json",
        {"content_sha256": expected_hash, "holdings": full_holdings},
    )

    validation = validate_candidate(public, candidate, history)

    assert validation.passed
