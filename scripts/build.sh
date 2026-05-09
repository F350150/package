#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

VERSION="${1:-}"
if [[ -z "${VERSION}" ]]; then
  echo "Usage: $0 <package-version>"
  echo "Example: $0 26.0.RC1"
  exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl not found in PATH"
  exit 1
fi

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "pyinstaller not found in PATH"
  exit 1
fi

CONFIG_FILE="${ROOT_DIR}/src/package_manager/config.py"
DER_CANONICAL="${ROOT_DIR}/pems/huawei_integrity_root_ca_g2.der"
DER_FALLBACK="${ROOT_DIR}/Huawei Integrity Root CA - G2.der"
INTERNAL_DIR="${ROOT_DIR}/_internal_build"
INTERNAL_OPENSSL_BIN_DIR="${INTERNAL_DIR}/openssl/bin"
INTERNAL_OPENSSL_LIB_DIR="${INTERNAL_DIR}/openssl/lib"
INTERNAL_OPENSSL_PEMS_DIR="${INTERNAL_DIR}/openssl/pems"
INTERNAL_PACKAGES_DIR="${INTERNAL_DIR}/packages"

mkdir -p "${ROOT_DIR}/pems"
if [[ ! -f "${DER_CANONICAL}" ]]; then
  if [[ -f "${DER_FALLBACK}" ]]; then
    cp -f "${DER_FALLBACK}" "${DER_CANONICAL}"
  else
    echo "DER file not found: ${DER_CANONICAL}"
    echo "Place root DER certificate under pems/huawei_integrity_root_ca_g2.der"
    exit 1
  fi
fi

python - <<'PY' "${CONFIG_FILE}" "${VERSION}"
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
version = sys.argv[2]
text = path.read_text(encoding="utf-8")
pattern = r'^PACKAGE_VERSION\s*=\s*"([^"]+)"$'
match = re.search(pattern, text, flags=re.M)
if not match:
    raise SystemExit("Failed to find PACKAGE_VERSION in config.py")

current = match.group(1)
if current == version:
    print(f"PACKAGE_VERSION already {version}, skip update")
    raise SystemExit(0)

updated = re.sub(pattern, f'PACKAGE_VERSION = "{version}"', text, flags=re.M)
path.write_text(updated, encoding="utf-8")
print(f"Updated PACKAGE_VERSION to {version}")
PY

rm -rf "${INTERNAL_DIR}"
mkdir -p "${INTERNAL_OPENSSL_BIN_DIR}" "${INTERNAL_OPENSSL_LIB_DIR}" "${INTERNAL_OPENSSL_PEMS_DIR}" "${INTERNAL_PACKAGES_DIR}"

openssl x509 -inform DER -in "${DER_CANONICAL}" -out "${INTERNAL_OPENSSL_PEMS_DIR}/huawei_integrity_root_ca_g2.pem"
OPENSSL_BIN_PATH="$(command -v openssl)"
OPENSSL_PREFIX_DIR="$(cd "$(dirname "${OPENSSL_BIN_PATH}")/.." && pwd)"
OPENSSL_LIB_SRC_DIR="${OPENSSL_PREFIX_DIR}/lib"

cp -f "${OPENSSL_BIN_PATH}" "${INTERNAL_OPENSSL_BIN_DIR}/openssl"
chmod +x "${INTERNAL_OPENSSL_BIN_DIR}/openssl"

for lib in libssl.3.dylib libcrypto.3.dylib; do
  if [[ -f "${OPENSSL_LIB_SRC_DIR}/${lib}" ]]; then
    cp -f "${OPENSSL_LIB_SRC_DIR}/${lib}" "${INTERNAL_OPENSSL_LIB_DIR}/${lib}"
  fi
done

cd "${ROOT_DIR}"
export PYINSTALLER_CONFIG_DIR="${ROOT_DIR}/.pyinstaller"
pyinstaller --noconfirm --clean --onedir --name package-manager src/package_manager/main.py

DIST_APP_DIR="${ROOT_DIR}/dist/package-manager"
DIST_INTERNAL_DIR="${DIST_APP_DIR}/_internal"
DIST_CONFIG_DIR="${DIST_APP_DIR}/config"
mkdir -p "${DIST_INTERNAL_DIR}"
cp -R "${INTERNAL_DIR}/." "${DIST_INTERNAL_DIR}/"
mkdir -p "${DIST_CONFIG_DIR}"
cp -f "${ROOT_DIR}/config/packages.yaml" "${DIST_CONFIG_DIR}/packages.yaml"
rm -rf "${DIST_APP_DIR}/_internel"

echo "Build finished"
echo "Binary: ${DIST_APP_DIR}/package-manager"
echo "Internal deps: ${DIST_INTERNAL_DIR}/openssl"
echo "Download cache dir: ${DIST_INTERNAL_DIR}/packages"
