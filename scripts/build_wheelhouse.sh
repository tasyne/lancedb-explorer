#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3.12}"
OUTPUT_DIR="${1:-wheelhouse}"

mkdir -p "${OUTPUT_DIR}"
"${PYTHON_BIN}" -m pip wheel --wheel-dir "${OUTPUT_DIR}" '.[dev]'

printf 'Wheelhouse created at %s\n' "${OUTPUT_DIR}"
printf 'Offline install: %s -m pip install --no-index --find-links %s lance-explorer\n' \
  "${PYTHON_BIN}" "${OUTPUT_DIR}"
