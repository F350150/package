#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# quick_start.sh
#
# 目标：一条命令完成“构建 + 运行”流程。
#
# 流程包含：
# 1) 环境与依赖检查
# 2) （可选）单元测试
# 3) 调用 build.sh 完成打包
# 4) 校验产物结构（_internal/openssl 等）
# 5) 运行产物（先 --list-packages，再执行安装）
#
# 说明：
# - 安装路径由 config.py 中每个 PackageConfig.install_dir 决定。
# - 脚本不会尝试 sudo，避免交互式密码问题和越权行为。
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_SCRIPT="${ROOT_DIR}/scripts/build.sh"

# -----------------------------
# 默认参数
# -----------------------------
VERSION="26.0.RC1"
PRODUCT_NAME="tiancheng"
PACKAGE_ID=""
LIST_ONLY="false"
SKIP_TESTS="false"

# -----------------------------
# 用法说明
# -----------------------------
usage() {
  cat <<'EOF'
Usage:
  ./scripts/quick_start.sh [options]

Options:
  --version <ver>       构建版本号（默认: 26.0.RC1）
  --name <product>      按产品名安装（默认: tiancheng）
  --package-id <id>     按 package-id 安装（优先级高于 --name）
  --list-only           只构建并列包，不执行安装
  --skip-tests          跳过 pytest
  -h, --help            查看帮助

Examples:
  ./scripts/quick_start.sh
  ./scripts/quick_start.sh --version 26.0.RC1 --name tiancheng
  ./scripts/quick_start.sh --package-id tiancheng-linux-arm64-tar-gz
  ./scripts/quick_start.sh --list-only
EOF
}

# -----------------------------
# 参数解析
# -----------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="${2:-}"
      shift 2
      ;;
    --name)
      PRODUCT_NAME="${2:-}"
      shift 2
      ;;
    --package-id)
      PACKAGE_ID="${2:-}"
      shift 2
      ;;
    --list-only)
      LIST_ONLY="true"
      shift
      ;;
    --skip-tests)
      SKIP_TESTS="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

# -----------------------------
# 基础校验
# -----------------------------
if [[ -z "${VERSION}" ]]; then
  echo "--version 不能为空"
  exit 1
fi

if [[ ! -x "${BUILD_SCRIPT}" ]]; then
  echo "build 脚本不存在或不可执行: ${BUILD_SCRIPT}"
  exit 1
fi

# DER 证书检查：优先 pems 目录，兼容根目录旧文件名
DER_PRIMARY="${ROOT_DIR}/pems/huawei_integrity_root_ca_g2.der"
DER_FALLBACK="${ROOT_DIR}/Huawei Integrity Root CA - G2.der"
if [[ ! -f "${DER_PRIMARY}" && ! -f "${DER_FALLBACK}" ]]; then
  echo "未找到 DER 证书。请准备以下任一文件："
  echo "  - ${DER_PRIMARY}"
  echo "  - ${DER_FALLBACK}"
  exit 1
fi

# 必要命令检查
for cmd in python openssl pyinstaller; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "命令不存在: ${cmd}"
    exit 1
  fi
done

# -----------------------------
# 1) （可选）执行测试
# -----------------------------
cd "${ROOT_DIR}"
if [[ "${SKIP_TESTS}" != "true" ]]; then
  echo "[1/5] 运行单元测试..."
  pytest
else
  echo "[1/5] 跳过单元测试"
fi

# -----------------------------
# 2) 构建产物
# -----------------------------
echo "[2/5] 执行构建: version=${VERSION}"
"${BUILD_SCRIPT}" "${VERSION}"

DIST_DIR="${ROOT_DIR}/dist/package-manager"
BIN_PATH="${DIST_DIR}/package-manager"
INTERNAL_DIR="${DIST_DIR}/_internal"
OPENSSL_BIN="${INTERNAL_DIR}/openssl/bin/openssl"
PEM_PATH="${INTERNAL_DIR}/openssl/pems/huawei_integrity_root_ca_g2.pem"
PKG_DIR="${INTERNAL_DIR}/packages"

# -----------------------------
# 3) 校验产物结构
# -----------------------------
echo "[3/5] 校验产物结构..."
for p in "${BIN_PATH}" "${INTERNAL_DIR}" "${OPENSSL_BIN}" "${PEM_PATH}" "${PKG_DIR}"; do
  if [[ ! -e "${p}" ]]; then
    echo "产物缺失: ${p}"
    exit 1
  fi
done

# -----------------------------
# 4) 列包（确认运行时解析结果）
# -----------------------------
echo "[4/5] 列出可安装包..."
"${BIN_PATH}" --list-packages

# list-only 模式直接结束
if [[ "${LIST_ONLY}" == "true" ]]; then
  echo "[5/5] 已按 --list-only 结束（未执行安装）"
  exit 0
fi

# -----------------------------
# 5) 执行安装
# -----------------------------
INSTALL_CMD=("${BIN_PATH}")

if [[ -n "${PACKAGE_ID}" ]]; then
  INSTALL_CMD+=(--package-id "${PACKAGE_ID}")
else
  INSTALL_CMD+=(--name "${PRODUCT_NAME}")
fi

echo "[5/5] 执行安装命令: ${INSTALL_CMD[*]}"
"${INSTALL_CMD[@]}"

echo "Quick start 完成。"
