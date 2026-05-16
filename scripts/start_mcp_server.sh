#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOST="${PACKAGE_MANAGER_MCP_HOST:-0.0.0.0}"
PORT="${PACKAGE_MANAGER_MCP_PORT:-8800}"
PATH_NAME="${PACKAGE_MANAGER_MCP_PATH:-/mcp}"

BINARY_PATH="${PACKAGE_MANAGER_BINARY_PATH:-/opt/package-manager/current/package-manager}"
CONFIG_FILE="${PACKAGE_MANAGER_CONFIG_FILE:-/opt/package-manager/current/config/packages.yaml}"
STATE_FILE="${PACKAGE_MANAGER_INSTALL_STATE_FILE:-/opt/package-manager/current/.package-manager/.install_state.yaml}"

AUTH_DISABLED="${PACKAGE_MANAGER_MCP_AUTH_DISABLED:-false}"
TOKEN="${PACKAGE_MANAGER_MCP_TOKEN:-}"
TOKEN_SCOPES="${PACKAGE_MANAGER_MCP_TOKEN_SCOPES:-pm:all}"
HMAC_SECRET="${PACKAGE_MANAGER_MCP_HMAC_SECRET:-}"
ALLOW_AUTH_DISABLED_NONLOCAL="${PACKAGE_MANAGER_MCP_ALLOW_AUTH_DISABLED_NONLOCAL:-false}"

if [[ "${AUTH_DISABLED}" != "true" && -z "${TOKEN}" && -z "${HMAC_SECRET}" ]]; then
  echo "Either PACKAGE_MANAGER_MCP_TOKEN or PACKAGE_MANAGER_MCP_HMAC_SECRET is required when auth is enabled."
  echo "Set PACKAGE_MANAGER_MCP_AUTH_DISABLED=true only for local debug."
  exit 1
fi

if [[ "${AUTH_DISABLED}" == "true" ]]; then
  if [[ "${HOST}" != "127.0.0.1" && "${HOST}" != "localhost" && "${HOST}" != "::1" && "${ALLOW_AUTH_DISABLED_NONLOCAL}" != "true" ]]; then
    echo "Refuse to start with auth disabled on non-loopback host=${HOST}."
    echo "If you really need this for temporary debug, set PACKAGE_MANAGER_MCP_ALLOW_AUTH_DISABLED_NONLOCAL=true."
    exit 1
  fi
fi

export PYTHONPATH="${ROOT_DIR}/src:${PYTHONPATH:-}"

CMD=(
  python -m package_manager.mcp_server
  --host "${HOST}"
  --port "${PORT}"
  --path "${PATH_NAME}"
  --binary-path "${BINARY_PATH}"
  --config-file "${CONFIG_FILE}"
  --state-file "${STATE_FILE}"
)

if [[ "${AUTH_DISABLED}" == "true" ]]; then
  CMD+=(--auth-disabled)
  if [[ "${ALLOW_AUTH_DISABLED_NONLOCAL}" == "true" ]]; then
    CMD+=(--allow-auth-disabled-nonlocal)
  fi
else
  if [[ -n "${TOKEN}" ]]; then
    CMD+=(--token "${TOKEN}" --token-scopes "${TOKEN_SCOPES}")
  fi
  if [[ -n "${HMAC_SECRET}" ]]; then
    CMD+=(--hmac-secret "${HMAC_SECRET}")
  fi
fi

echo "Starting package-manager MCP server..."
echo "host=${HOST} port=${PORT} path=${PATH_NAME}"
echo "binary=${BINARY_PATH}"
echo "config=${CONFIG_FILE}"
echo "state=${STATE_FILE}"

exec "${CMD[@]}"
