#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_BIN="${PACKAGE_MANAGER_PYTHON_BIN:-/opt/cpython-3.11/bin/python3.11}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export PACKAGE_MANAGER_CONFIG_FILE="${PACKAGE_MANAGER_CONFIG_FILE:-/opt/package-manager/current/config/packages.yaml}"
export PACKAGE_MANAGER_INSTALL_STATE_FILE="${PACKAGE_MANAGER_INSTALL_STATE_FILE:-/opt/package-manager/current/.package-manager/.install_state.yaml}"

exec "${PY_BIN}" -m package_manager.main "$@"
