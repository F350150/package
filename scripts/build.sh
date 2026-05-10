#!/usr/bin/env bash
# 构建脚本：
# 1) 预校验构建依赖与输入
# 2) 组装内置 openssl 运行时目录
# 3) 使用 PyInstaller 打包
# 4) 渲染运行时 YAML 并落盘到 dist
set -euo pipefail

# 计算脚本目录与项目根目录，避免依赖调用时的当前工作目录。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 必填构建版本参数，用于渲染 packages.yaml 中的版本占位符。
VERSION="${1:-}"
if [[ -z "${VERSION}" ]]; then
  echo "Usage: $0 <package-version>"
  echo "Example: $0 26.0.RC1"
  exit 1
fi

# 依赖检查：验签链路依赖 openssl，打包链路依赖 pyinstaller。
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

# 根证书准备：
# - 优先使用 canonical 路径
# - 兼容历史 fallback 文件名
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

# 构建期模板必须存在，否则运行时配置无法生成。
if [[ ! -f "${CONFIG_TEMPLATE_FILE}" ]]; then
  echo "Config template file not found: ${CONFIG_TEMPLATE_FILE}"
  exit 1
fi

# 每次构建都重建内部依赖目录，确保产物纯净可复现。
rm -rf "${INTERNAL_DIR}"
mkdir -p "${INTERNAL_OPENSSL_BIN_DIR}" "${INTERNAL_OPENSSL_LIB_DIR}" "${INTERNAL_OPENSSL_PEMS_DIR}" "${INTERNAL_PACKAGES_DIR}"

# DER -> PEM，供运行时 openssl 验签使用。
openssl x509 -inform DER -in "${DER_CANONICAL}" -out "${INTERNAL_OPENSSL_PEMS_DIR}/huawei_integrity_root_ca_g2.pem"
OPENSSL_BIN_PATH="$(command -v openssl)"

# 拷贝 openssl 可执行文件到内置目录。
cp -f "${OPENSSL_BIN_PATH}" "${INTERNAL_OPENSSL_BIN_DIR}/openssl"
chmod +x "${INTERNAL_OPENSSL_BIN_DIR}/openssl"

copy_openssl_runtime_libs() {
  # 收集 openssl 运行时动态库（libssl/libcrypto），
  # 避免运行时链接到宿主机不兼容的系统库。
  local bin_path="$1"
  local dst_dir="$2"
  local copied=0

  # Linux 优先使用 ldd，macOS 使用 otool。
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

  # 一个都没收集到时直接失败，避免生成不可用产物。
  if [[ ${copied} -eq 0 ]]; then
    echo "Failed to collect openssl runtime libs for ${bin_path} (libssl/libcrypto)"
    exit 1
  fi
}

# 收集内置 openssl 所需运行库。
copy_openssl_runtime_libs "${OPENSSL_BIN_PATH}" "${INTERNAL_OPENSSL_LIB_DIR}"

# 执行 PyInstaller 打包。
cd "${ROOT_DIR}"
export PYINSTALLER_CONFIG_DIR="${ROOT_DIR}/.pyinstaller"
pyinstaller --noconfirm --clean --onedir --name package-manager src/package_manager/main.py

# 组装 dist 目录结构。
DIST_APP_DIR="${ROOT_DIR}/dist/package-manager"
DIST_INTERNAL_DIR="${DIST_APP_DIR}/_internal"
DIST_CONFIG_DIR="${DIST_APP_DIR}/config"
mkdir -p "${DIST_INTERNAL_DIR}"
cp -R "${INTERNAL_DIR}/." "${DIST_INTERNAL_DIR}/"
mkdir -p "${DIST_CONFIG_DIR}"

# 构建期渲染运行时配置（替换 ${PACKAGE_VERSION}）。
PYTHONPATH="${ROOT_DIR}/src" python3 -m package_manager.build_config_renderer \
  --template "${CONFIG_TEMPLATE_FILE}" \
  --output "${DIST_CONFIG_DIR}/packages.yaml" \
  --version "${VERSION}"

# 清理历史误拼目录（兼容旧脚本遗留）。
rm -rf "${DIST_APP_DIR}/_internel"

echo "Build finished"
echo "Binary: ${DIST_APP_DIR}/package-manager"
echo "Internal deps: ${DIST_INTERNAL_DIR}/openssl"
echo "Download cache dir: ${DIST_INTERNAL_DIR}/packages"
