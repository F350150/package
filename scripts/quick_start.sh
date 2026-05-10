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
# 5) 运行产物（按 --name 执行安装）
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
PRODUCT_NAME="DevKit-Porting-Advisor"
SKIP_TESTS="false"
TEST_PORTING_INSTALLERS="false"
CONTAINER_NAME=""
CONTAINER_BOOTSTRAP_DEPS="true"
FORWARD_ARGS=()

# -----------------------------
# 用法说明
# -----------------------------
usage() {
  cat <<'EOF'
Usage:
  ./scripts/quick_start.sh [options]

Options:
  --version <ver>       构建版本号（默认: 26.0.RC1）
  --name <product>      按产品名安装（默认: DevKit-Porting-Advisor）
  --skip-tests          跳过 pytest
  --test-porting-installers  依次测试 DevKit-Porting-Advisor 与 devkit-porting 两个 installer
  --container <name>    在指定容器里执行完整 quick_start 测试流程
  --container-no-bootstrap  容器模式下不自动安装 pytest/pyinstaller
  -h, --help            查看帮助

Examples:
  ./scripts/quick_start.sh
  ./scripts/quick_start.sh --version 26.0.RC1 --name DevKit-Porting-Advisor
  ./scripts/quick_start.sh --container openeuler-arm --test-porting-installers
EOF
}

run_inside_container() {
  local container_name="$1"
  local run_dir="/root/package_e2e_$(date +%Y%m%d_%H%M%S)"
  local cmd_parts=()
  local container_cmd=""
  local quoted_args=()

  if ! command -v docker >/dev/null 2>&1; then
    echo "容器模式需要 docker 命令"
    exit 1
  fi

  echo "[container] 复制项目到容器 ${container_name}:${run_dir}"
  docker cp "${ROOT_DIR}/." "${container_name}:${run_dir}"

  if [[ "${CONTAINER_BOOTSTRAP_DEPS}" == "true" ]]; then
    cmd_parts+=("python3 -m pip --version >/dev/null 2>&1 || (python3 -m ensurepip --upgrade >/dev/null 2>&1 || true)")
    cmd_parts+=("python3 -m pip install --no-cache-dir pytest pyinstaller pyyaml")
  fi

  for arg in "${FORWARD_ARGS[@]}"; do
    quoted_args+=("$(printf '%q' "$arg")")
  done

  cmd_parts+=("INTERNAL_CONTAINER_RUN=1 ./scripts/quick_start.sh ${quoted_args[*]}")
  container_cmd="${cmd_parts[0]}"
  for ((i = 1; i < ${#cmd_parts[@]}; i++)); do
    container_cmd="${container_cmd} && ${cmd_parts[$i]}"
  done

  echo "[container] 在容器内执行 quick_start..."
  docker exec "${container_name}" /bin/bash -lc "cd '${run_dir}' && ${container_cmd}"
}

# -----------------------------
# 参数解析
# -----------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="${2:-}"
      FORWARD_ARGS+=("$1" "$2")
      shift 2
      ;;
    --name)
      PRODUCT_NAME="${2:-}"
      FORWARD_ARGS+=("$1" "$2")
      shift 2
      ;;
    --skip-tests)
      SKIP_TESTS="true"
      FORWARD_ARGS+=("$1")
      shift
      ;;
    --test-porting-installers)
      TEST_PORTING_INSTALLERS="true"
      FORWARD_ARGS+=("$1")
      shift
      ;;
    --container)
      CONTAINER_NAME="${2:-}"
      shift 2
      ;;
    --container-no-bootstrap)
      CONTAINER_BOOTSTRAP_DEPS="false"
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

if [[ -n "${CONTAINER_NAME}" && "${INTERNAL_CONTAINER_RUN:-0}" != "1" ]]; then
  if [[ -z "${CONTAINER_NAME}" ]]; then
    echo "--container 不能为空"
    exit 1
  fi
  run_inside_container "${CONTAINER_NAME}"
  exit $?
fi

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

if ! python -c "import yaml" >/dev/null 2>&1; then
  echo "Python 模块缺失: pyyaml（请执行: python -m pip install pyyaml）"
  exit 1
fi

# -----------------------------
# 1) （可选）执行测试
# -----------------------------
cd "${ROOT_DIR}"
if [[ "${SKIP_TESTS}" != "true" ]]; then
  echo "[1/4] 运行单元测试..."
  pytest
else
  echo "[1/4] 跳过单元测试"
fi

# -----------------------------
# 2) 构建产物
# -----------------------------
echo "[2/4] 执行构建: version=${VERSION}"
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
echo "[3/4] 校验产物结构..."
for p in "${BIN_PATH}" "${INTERNAL_DIR}" "${OPENSSL_BIN}" "${PEM_PATH}" "${PKG_DIR}"; do
  if [[ ! -e "${p}" ]]; then
    echo "产物缺失: ${p}"
    exit 1
  fi
done

# -----------------------------
# 4) 执行安装
# -----------------------------
if [[ "${TEST_PORTING_INSTALLERS}" == "true" ]]; then
  echo "[4/4] 依次测试两个 installer: DevKit-Porting-Advisor + devkit-porting"
  "${BIN_PATH}" --name "DevKit-Porting-Advisor"
  if command -v rpm >/dev/null 2>&1; then
    "${BIN_PATH}" --name "devkit-porting"
  else
    echo "WARNING: rpm 命令不存在，当前主机跳过 devkit-porting installer 测试"
  fi
  echo "Quick start 完成（porting installers）。"
  exit 0
fi

INSTALL_CMD=("${BIN_PATH}")
INSTALL_CMD+=(--name "${PRODUCT_NAME}")

echo "[4/4] 执行安装命令: ${INSTALL_CMD[*]}"
"${INSTALL_CMD[@]}"

echo "Quick start 完成。"
