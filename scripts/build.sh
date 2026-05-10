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

CONFIG_TEMPLATE_FILE="${ROOT_DIR}/config/packages.template.yaml"
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

if [[ ! -f "${CONFIG_TEMPLATE_FILE}" ]]; then
  echo "Config template file not found: ${CONFIG_TEMPLATE_FILE}"
  exit 1
fi

rm -rf "${INTERNAL_DIR}"
mkdir -p "${INTERNAL_OPENSSL_BIN_DIR}" "${INTERNAL_OPENSSL_LIB_DIR}" "${INTERNAL_OPENSSL_PEMS_DIR}" "${INTERNAL_PACKAGES_DIR}"

openssl x509 -inform DER -in "${DER_CANONICAL}" -out "${INTERNAL_OPENSSL_PEMS_DIR}/huawei_integrity_root_ca_g2.pem"
OPENSSL_BIN_PATH="$(command -v openssl)"

cp -f "${OPENSSL_BIN_PATH}" "${INTERNAL_OPENSSL_BIN_DIR}/openssl"
chmod +x "${INTERNAL_OPENSSL_BIN_DIR}/openssl"

copy_openssl_runtime_libs() {
  local bin_path="$1"
  local dst_dir="$2"
  local copied=0

  if command -v ldd >/dev/null 2>&1; then
    while IFS= read -r lib_path; do
      if [[ -f "${lib_path}" ]]; then
        cp -f "${lib_path}" "${dst_dir}/"
        copied=$((copied + 1))
      fi
    done < <(ldd "${bin_path}" | awk '
      /libssl\.so|libcrypto\.so/ {
        for (i = 1; i <= NF; i++) {
          if ($i ~ /^\//) {
            print $i;
            break;
          }
        }
      }
    ' | sort -u)
  elif command -v otool >/dev/null 2>&1; then
    while IFS= read -r lib_path; do
      if [[ -f "${lib_path}" ]]; then
        cp -f "${lib_path}" "${dst_dir}/"
        copied=$((copied + 1))
      fi
    done < <(otool -L "${bin_path}" | awk '
      /libssl.*\.dylib|libcrypto.*\.dylib/ {
        print $1;
      }
    ' | sort -u)
  fi

  if [[ ${copied} -eq 0 ]]; then
    echo "Failed to collect openssl runtime libs for ${bin_path} (libssl/libcrypto)"
    exit 1
  fi
}

copy_openssl_runtime_libs "${OPENSSL_BIN_PATH}" "${INTERNAL_OPENSSL_LIB_DIR}"

cd "${ROOT_DIR}"
export PYINSTALLER_CONFIG_DIR="${ROOT_DIR}/.pyinstaller"
pyinstaller --noconfirm --clean --onedir --name package-manager src/package_manager/main.py

DIST_APP_DIR="${ROOT_DIR}/dist/package-manager"
DIST_INTERNAL_DIR="${DIST_APP_DIR}/_internal"
DIST_CONFIG_DIR="${DIST_APP_DIR}/config"
mkdir -p "${DIST_INTERNAL_DIR}"
cp -R "${INTERNAL_DIR}/." "${DIST_INTERNAL_DIR}/"
mkdir -p "${DIST_CONFIG_DIR}"
PYTHONPATH="${ROOT_DIR}/src" python3 -m package_manager.build_config_renderer \
  --template "${CONFIG_TEMPLATE_FILE}" \
  --output "${DIST_CONFIG_DIR}/packages.yaml" \
  --version "${VERSION}"
rm -rf "${DIST_APP_DIR}/_internel"

echo "Build finished"
echo "Binary: ${DIST_APP_DIR}/package-manager"
echo "Internal deps: ${DIST_INTERNAL_DIR}/openssl"
echo "Download cache dir: ${DIST_INTERNAL_DIR}/packages"
