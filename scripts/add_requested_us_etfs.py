"""Add the August 2026 requested US ETF coverage expansion.

This is intentionally idempotent so the exact seed change can be reviewed and
replayed without hand-editing the large JSON files.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed"


FUNDS = [
    # ticker, name, benchmark, asset class, Chinese display name
    ("VXUS", "Vanguard Total International Stock ETF", "FTSE Global All Cap ex US", "equity", "Vanguard 全球（美國除外）股票 ETF"),
    ("ITOT", "iShares Core S&P Total U.S. Stock Market ETF", "S&P Total Market", "equity", "iShares 核心標普美國全市場股票 ETF"),
    ("QQQM", "Invesco NASDAQ 100 ETF", "NASDAQ-100", "equity", "景順 NASDAQ 100 ETF"),
    ("RSP", "Invesco S&P 500 Equal Weight ETF", "S&P 500 Equal Weight", "equity", "景順標普 500 等權重 ETF"),
    ("VUG", "Vanguard Growth ETF", "CRSP US Large Cap Growth", "equity", "Vanguard 美國大型成長股 ETF"),
    ("VTV", "Vanguard Value ETF", "CRSP US Large Cap Value", "equity", "Vanguard 美國大型價值股 ETF"),
    ("IWF", "iShares Russell 1000 Growth ETF", "Russell 1000 Growth", "equity", "iShares 羅素 1000 成長股 ETF"),
    ("IWD", "iShares Russell 1000 Value ETF", "Russell 1000 Value", "equity", "iShares 羅素 1000 價值股 ETF"),
    ("SCHG", "Schwab U.S. Large-Cap Growth ETF", "Dow Jones U.S. Large-Cap Growth Total Stock Market", "equity", "Schwab 美國大型成長股 ETF"),
    ("VO", "Vanguard Mid-Cap ETF", "CRSP US Mid Cap", "equity", "Vanguard 美國中型股 ETF"),
    ("VB", "Vanguard Small-Cap ETF", "CRSP US Small Cap", "equity", "Vanguard 美國小型股 ETF"),
    ("IJH", "iShares Core S&P Mid-Cap ETF", "S&P MidCap 400", "equity", "iShares 核心標普中型股 ETF"),
    ("IJR", "iShares Core S&P Small-Cap ETF", "S&P SmallCap 600", "equity", "iShares 核心標普小型股 ETF"),
    ("IEFA", "iShares Core MSCI EAFE ETF", "MSCI EAFE IMI", "equity", "iShares 核心 MSCI EAFE ETF"),
    ("IEMG", "iShares Core MSCI Emerging Markets ETF", "MSCI Emerging Markets Investable Market", "equity", "iShares 核心 MSCI 新興市場 ETF"),
    ("EFA", "iShares MSCI EAFE ETF", "MSCI EAFE", "equity", "iShares MSCI EAFE ETF"),
    ("IXUS", "iShares Core MSCI Total International Stock ETF", "MSCI ACWI ex USA IMI", "equity", "iShares 核心 MSCI 全球（美國除外）股票 ETF"),
    ("SCHF", "Schwab International Equity ETF", "FTSE Developed ex US", "equity", "Schwab 國際股票 ETF"),
    ("BNDX", "Vanguard Total International Bond ETF", "Bloomberg Global Aggregate ex-USD Float Adjusted RIC Capped", "fixed_income", "Vanguard 全球（美國除外）債券 ETF"),
    ("VCIT", "Vanguard Intermediate-Term Corporate Bond ETF", "Bloomberg U.S. 5-10 Year Corporate Bond", "fixed_income", "Vanguard 美國中期公司債券 ETF"),
    ("VGT", "Vanguard Information Technology ETF", "MSCI US Investable Market Information Technology 25/50", "equity", "Vanguard 美國資訊科技 ETF"),
    ("IAU", "iShares Gold Trust", "LBMA Gold Price", "commodity", "iShares 黃金信託"),
    ("VYM", "Vanguard High Dividend Yield ETF", "FTSE High Dividend Yield", "equity", "Vanguard 美國高股息 ETF"),
    ("SPYM", "State Street SPDR Portfolio S&P 500 ETF", "S&P 500", "equity", "State Street SPDR 投資組合標普 500 ETF"),
    ("SPLG", "SPDR Portfolio S&P 500 ETF", "S&P 500", "equity", "SPDR 投資組合標普 500 ETF"),
    ("SCHX", "Schwab U.S. Large-Cap ETF", "Dow Jones U.S. Large-Cap Total Stock Market", "equity", "Schwab 美國大型股 ETF"),
    ("VV", "Vanguard Large-Cap ETF", "CRSP US Large Cap", "equity", "Vanguard 美國大型股 ETF"),
    ("VEU", "Vanguard FTSE All-World ex-US ETF", "FTSE All-World ex US", "equity", "Vanguard 富時全球（美國除外）ETF"),
    ("VXF", "Vanguard Extended Market ETF", "S&P Completion", "equity", "Vanguard 美國延伸市場 ETF"),
    ("VBR", "Vanguard Small-Cap Value ETF", "CRSP US Small Cap Value", "equity", "Vanguard 美國小型價值股 ETF"),
    ("IVW", "iShares S&P 500 Growth ETF", "S&P 500 Growth", "equity", "iShares 標普 500 成長股 ETF"),
    ("LYTE", "Roundhill Photonics & Optics ETF", "Actively Managed Photonics and Optics Equity", "equity", "Roundhill 光子與光學 ETF"),
]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, rows) -> None:
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    entities_path = SEED / "entities.json"
    translations_path = SEED / "translations_zh.json"
    entities = load(entities_path)
    translations = load(translations_path)
    entity_ids = {row["etf_id"] for row in entities}
    translation_ids = {row["etf_id"] for row in translations}

    for ticker, name, benchmark, asset_class, name_zh in FUNDS:
        etf_id = f"US-{ticker}"
        if etf_id not in entity_ids:
            row = {
                "etf_id": etf_id,
                "ticker": ticker,
                "quote_symbol": ticker,
                "name": name,
                "short_name": ticker,
                "listing_market": "US",
                "listing_exchange": "US",
                "currency": "USD",
                "benchmark_symbol": "SPY",
                "benchmark_name": benchmark,
                "asset_class": asset_class,
                "active": True,
                "product_status": "active",
                "management_style": "active" if ticker == "LYTE" else "passive",
            }
            if ticker == "LYTE":
                row.update(
                    {
                        "issuer": "Roundhill Financial Inc.",
                        "is_thematic": True,
                        "inception_date": "2026-08-06",
                        "first_seen_at": "2026-08-25",
                    }
                )
            entities.append(row)
            entity_ids.add(etf_id)
        if etf_id not in translation_ids:
            translations.append({"etf_id": etf_id, "name_zh": name_zh})
            translation_ids.add(etf_id)

    save(entities_path, entities)
    save(translations_path, translations)
    print(json.dumps({"requested": len(FUNDS), "entities": len(entities)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
