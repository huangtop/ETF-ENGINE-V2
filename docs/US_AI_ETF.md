# US AI ETF universe

ETF Engine v2.1 contains a curated 50-fund AI value-chain universe. It is intentionally broader than funds whose names contain “AI”. The taxonomy covers:

- AI core, generative AI and software
- GPU, semiconductor, memory and HBM
- cloud, networking, cybersecurity and edge AI
- robotics, autonomous driving and space systems
- data centers and digital infrastructure
- electricity grids, nuclear and uranium used by AI infrastructure

Every fund can have multiple `ai_layer` classifications. Classification is analytical metadata, not a statement that the fund is a pure-play AI product.

## Holdings outputs

After the US pipeline runs:

- `data/public/etf/US-SMH.json` includes `top_holdings` and concentration summaries.
- `data/public/holdings/NVDA.json` lists ETFs holding NVIDIA, ordered by weight.
- `data/public/holdings_index.json` is the complete reverse holding index.
- `data/public/overlap/US-SMH__US-SOXX.json` contains weighted overlap and shared holdings.
- `data/public/overlap_index.json` contains compact pair summaries.

Weighted overlap is calculated as the sum of the lower portfolio weight for each shared security.

Holdings are fetched through `yfinance.Ticker(...).funds_data.top_holdings`. On provider failure, the last successful local cache is retained.
