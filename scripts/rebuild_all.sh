#!/usr/bin/env bash
set -euo pipefail
python -m etf_engine.services.sync_tw_entities --minimum-tw-count 200
python -m etf_engine.services.build_classifications
python -m etf_engine.services.sync_holdings --market all
python -m etf_engine.cli run --market all
