#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3}"

"$PYTHON" -m etf_engine.cli sync-tw-entities --minimum-tw-count 200
"$PYTHON" -m etf_engine.cli build-classifications
"$PYTHON" -m etf_engine.cli validate
"$PYTHON" -m etf_engine.cli sync-holdings --market all
"$PYTHON" -m etf_engine.cli run --market all
