#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONDA_BIN="${CONDA_BIN:-conda}"
ENV_NAME="${ENV_NAME:-coral-paraview}"
PYTHON_VERSION="${PYTHON_VERSION:-3.10}"

echo "Repo root: ${REPO_ROOT}"
echo "Using conda: ${CONDA_BIN}"
echo "Creating environment: ${ENV_NAME}"
echo "Python version: ${PYTHON_VERSION}"

if ! command -v "${CONDA_BIN}" >/dev/null 2>&1; then
    echo "Error: ${CONDA_BIN} not found."
    echo "Set CONDA_BIN=/path/to/conda and rerun."
    exit 1
fi

"${CONDA_BIN}" create -y -n "${ENV_NAME}" -c conda-forge \
    "python=${PYTHON_VERSION}" \
    paraview \
    trame \
    trame-vtk \
    trame-vuetify

"${CONDA_BIN}" run -n "${ENV_NAME}" python -c \
    "import sys, paraview, trame; print(f'python: {sys.version.split()[0]}'); print(f'paraview: {paraview.__file__}'); print(f'trame: {trame.__file__}')"

echo "Installing dev dependencies..."
"${CONDA_BIN}" run -n "${ENV_NAME}" python -m pip install --no-cache-dir \
    -r "${REPO_ROOT}/setup/requirements-dev.txt"

echo "Installing Playwright browser..."
"${CONDA_BIN}" run -n "${ENV_NAME}" python -m playwright install chromium

echo
echo "Conda environment '${ENV_NAME}' is ready."
echo "Run the app with:"
echo "${CONDA_BIN} run -n ${ENV_NAME} python ${REPO_ROOT}/app.py"
