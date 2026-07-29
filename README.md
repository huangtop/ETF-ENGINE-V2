# ETF Engine v2

以 GitHub Actions 自動更新台灣與美國 ETF 資料，產出 WordPress 可直接讀取的 JSON。

## 架構

```text
Provider → normalized prices → metrics → public JSON → WordPress cache → Chart.js
```

- 台股價格：TWSE 優先，Yahoo Finance 備援
- 美股價格：Yahoo Finance
- ETF 基本資料：seed entity + provider 補充
- 指標：報酬、Alpha、Beta、Sharpe、波動率、最大回撤、追蹤誤差
- 分類：多維分類，不再以單一類別 JSON 綁死 ETF
- 輸出：`data/public/`，WordPress 不必執行 Python

## 第一次使用

1. 建立新的 GitHub repository，將本專案全部上傳。
2. 在 Repository → Settings → Actions → General，允許 Actions 寫入 repository。
3. 手動執行 `ETF Daily Pipeline`。
4. 成功後，公開資料會出現在 `data/public/`。
5. 將 `wordpress/etf-engine-v2.php` 安裝為 WordPress 外掛，並在設定中填入 raw GitHub URL。

## 本機執行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m etf_engine.cli validate
python -m etf_engine.cli run --market all
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
```

## GitHub Secrets

目前核心流程不強制需要 API key。可選：

- `ALPHA_VANTAGE_API_KEY`：未來加入 Alpha Vantage provider 時使用

## WordPress shortcode

```text
[etf_engine_v2 market="TW" classification="strategy:high_dividend"]
[etf_engine_v2 market="US" classification="asset_class:equity"]
[etf_engine_v2 market="US" classification="strategy:dividend"]
```

## 資料輸出

- `data/public/manifest.json`
- `data/public/etfs.json`
- `data/public/classifications.json`
- `data/public/latest_metrics.json`
- `data/public/markets/TW.json`
- `data/public/markets/US.json`
- `data/public/etf/<etf_id>.json`

既有 `data/public/` 契約維持不變。每次 holdings provider 成功取得非空資料時，
另於 `data/history/holdings/` 記錄歷史：

- `manifest.json`：history schema、coverage 與更新統計。
- `snapshot_index.json`：每檔 ETF 的 current、previous 與內容 snapshot 索引。
- `observations.json`：每次成功檢查時間；內容相同時仍會新增 observation。
- `snapshots/`：immutable holdings 內容，僅在內容 hash 尚未出現時新增。

`observed_at` 是本系統成功觀察資料的時間，不代表 provider 的資料日期。
若來源未提供可靠日期，`provider_generated_at` 與 `provider_as_of` 皆為 `null`。

V031E.2B 會將內容變更的相鄰 observation 轉成未經推理的原始事件，供 AXIOM
唯讀取得：

- `data/public/history/holdings/manifest.json`
- `data/public/history/holdings/latest_changes.json`
- `data/public/history/holdings/<etf_id>.json`

事件類型為 `ENTERED_TOP_HOLDINGS`、`EXITED_TOP_HOLDINGS`、
`WEIGHT_INCREASED`、`WEIGHT_DECREASED` 與 `UNCHANGED`。首次快照沒有比較基準，
因此不產生事件；相同內容的重複 observation 也不產生重複 transition。ETF Engine
不提供 AXIOM identity mapping、重要性評分、估值、新聞或產業鏈推理。

## 重要設計

- `etf_id` 是永久識別碼，例如 `TW-0050`、`US-SPY`。
- `ticker` 是市場代碼，可能因供應商而不同。
- `quote_symbol` 是實際向資料供應商查詢的代碼。
- ETF 可以同時具有多個分類，不再重複維護於不同檔案。
- 股息 seed 值不再當作同一種資料；新版只保留明確定義的 metric。

## 台灣繁體顯示欄位

ETF 與持股的 canonical 英文名稱及永久識別碼維持不變，public JSON 另提供
`name_zh`／`holding_name_zh`、`display_name`、`display_label` 與
`bilingual_name`，讓 AXIOM 或其他前端自行選擇台灣化短標籤或中英雙語名稱。
未知譯名一律回退 provider 原名，不進行未審核的機器翻譯。

持股譯名維護於 `data/seed/holding_translations_zh.json`，可保存人工審核來源。
例如 IQMM 的 public display label 為
`(IQMM)ProShares GENIUS貨幣市場主動型ETF`，canonical `holding_name` 仍為
`ProShares GENIUS Money Market ETF`。

## 舊專案遷移

舊 JSON 已轉入 `data/seed/entities.json`、`classifications.json` 與 `metric_overrides.json`。
舊 CSV 前端暫時保留於 `legacy/` 供比對，但新 WordPress 外掛讀取 JSON。

## v2.1: US AI and holdings intelligence

- Expanded the US universe to 78 ETFs, including a curated 50-fund AI value-chain set.
- Added granular AI layers: memory/HBM, semiconductors, cloud, software, data centers, networking, cybersecurity, robotics, autonomous systems and AI power infrastructure.
- Added Top Holdings, Top-3/Top-10 concentration, stock-to-ETF reverse lookup and weighted ETF overlap analysis.
- See `docs/US_AI_ETF.md` for the taxonomy and public JSON endpoints.

cd /Users/xxx/Desktop/Python\ Code/Streamlit\ Project/ETF-Engine-v2 && source .venv/bin/activate && python -m etf_engine.cli run --market all
