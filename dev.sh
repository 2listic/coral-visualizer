#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_BIN="${CONDA_BIN:-/Users/heltai/anaconda3/bin/conda}"
ENV_NAME="${ENV_NAME:-coral-paraview}"

if [ ! -x "${CONDA_BIN}" ]; then
    echo "Error: conda not found at ${CONDA_BIN}"
    echo "Set CONDA_BIN=/path/to/conda and retry."
    exit 1
fi

eval "$("${CONDA_BIN}" shell.zsh hook)"
conda activate "${ENV_NAME}"

cd "${SCRIPT_DIR}"
exec python app.py --backend paraview --dev --hot-reload "$@"
