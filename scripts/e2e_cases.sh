#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# e2e_cases.sh
#
# 目标：执行 package-manager 端到端场景回归（按场景编号）
# 默认覆盖：S01-S16, S18-S20（显式跳过 S17）
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_SCRIPT="${ROOT_DIR}/scripts/build.sh"

VERSION="26.0.RC1"
CONTAINER_NAME=""
CONTAINER_BOOTSTRAP_DEPS="true"
SKIP_BUILD="false"
FORWARD_ARGS=()

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/e2e_cases.sh [options]

Options:
  --version <ver>               构建版本号（默认: 26.0.RC1）
  --skip-build                  跳过 build（要求 dist 已存在）
  --container <name>            在指定容器里执行场景
  --container-no-bootstrap      容器模式下不自动安装 pyinstaller/pyyaml
  -h, --help                    查看帮助

Examples:
  ./scripts/e2e_cases.sh
  ./scripts/e2e_cases.sh --container openeuler-arm
USAGE
}

run_inside_container() {
  local container_name="$1"
  local run_dir="/root/package_e2e_cases_$(date +%Y%m%d_%H%M%S)"
  local cmd_parts=()
  local quoted_args=()
  local container_cmd=""
  local forwarded_args=""

  if ! command -v docker >/dev/null 2>&1; then
    echo "容器模式需要 docker 命令"
    exit 1
  fi

  echo "[container] 复制项目到容器 ${container_name}:${run_dir}"
  docker cp "${ROOT_DIR}/." "${container_name}:${run_dir}"

  if [[ "${CONTAINER_BOOTSTRAP_DEPS}" == "true" ]]; then
    cmd_parts+=("python3 -m pip --version >/dev/null 2>&1 || (python3 -m ensurepip --upgrade >/dev/null 2>&1 || true)")
    cmd_parts+=("python3 -m pip install --no-cache-dir pyinstaller pyyaml")
  fi

  if [[ ${#FORWARD_ARGS[@]} -gt 0 ]]; then
    for arg in "${FORWARD_ARGS[@]}"; do
      quoted_args+=("$(printf '%q' "$arg")")
    done
  fi

  if [[ ${#quoted_args[@]} -gt 0 ]]; then
    forwarded_args="${quoted_args[*]}"
  fi
  cmd_parts+=("INTERNAL_CONTAINER_RUN=1 ./scripts/e2e_cases.sh ${forwarded_args}")
  container_cmd="${cmd_parts[0]}"
  local i
  for ((i = 1; i < ${#cmd_parts[@]}; i++)); do
    container_cmd+=" && ${cmd_parts[$i]}"
  done

  echo "[container] 在容器内执行 e2e 场景..."
  docker exec "${container_name}" /bin/bash -lc "cd '${run_dir}' && ${container_cmd}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="${2:-}"
      FORWARD_ARGS+=("$1" "$2")
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD="true"
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
  run_inside_container "${CONTAINER_NAME}"
  exit $?
fi

if [[ ! -x "${BUILD_SCRIPT}" ]]; then
  echo "build 脚本不存在或不可执行: ${BUILD_SCRIPT}"
  exit 1
fi

for cmd in python3 tar; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "命令不存在: ${cmd}"
    exit 1
  fi
done

if [[ "${SKIP_BUILD}" != "true" ]]; then
  echo "[prep] build version=${VERSION}"
  "${BUILD_SCRIPT}" "${VERSION}"
else
  echo "[prep] 跳过 build"
fi

DIST_DIR="${ROOT_DIR}/dist/package-manager"
BIN_PATH="${DIST_DIR}/package-manager"
BASE_CFG="${DIST_DIR}/config/packages.yaml"
OPENSSL_PEM="${DIST_DIR}/_internal/openssl/pems/huawei_integrity_root_ca_g2.pem"

if [[ ! -x "${BIN_PATH}" ]]; then
  echo "产物不存在: ${BIN_PATH}"
  exit 1
fi
if [[ ! -f "${BASE_CFG}" ]]; then
  echo "配置不存在: ${BASE_CFG}"
  exit 1
fi

LOG_ROOT="${ROOT_DIR}/e2e_logs"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="${LOG_ROOT}/${RUN_ID}"
mkdir -p "${LOG_DIR}"

PORTING_ID="Porting-Advisor-linux-arm64-tar-gz"
DEVKIT_ID="devkit-porting-linux-arm64-rpm"
PORTING_DIR="${DIST_DIR}/_internal/porting_cli"
PKG_ROOT="${DIST_DIR}/_internal/packages"
PORTING_PKG_DIR="${PKG_ROOT}/${PORTING_ID}"
DEVKIT_PKG_DIR="${PKG_ROOT}/${DEVKIT_ID}"

STATE_PORTING="${LOG_DIR}/state_porting.yaml"
STATE_DEVKIT="${LOG_DIR}/state_devkit.yaml"

TOTAL=0
PASSED=0
FAILED=0

run_case() {
  local sid="$1"
  local expected_rc="$2"
  shift 2
  local log_file="${LOG_DIR}/${sid}.log"
  local rc_file="${LOG_DIR}/${sid}.rc"
  local rc

  TOTAL=$((TOTAL + 1))
  echo "[run] ${sid}"
  set +e
  "$@" >"${log_file}" 2>&1
  rc=$?
  set -e
  echo "${rc}" >"${rc_file}"

  if [[ "${rc}" == "${expected_rc}" ]]; then
    PASSED=$((PASSED + 1))
    echo "[pass] ${sid} rc=${rc}"
    return 0
  fi

  FAILED=$((FAILED + 1))
  echo "[fail] ${sid} rc=${rc} expected=${expected_rc}"
  return 1
}

assert_log_contains() {
  local sid="$1"
  local pattern="$2"
  local log_file="${LOG_DIR}/${sid}.log"
  if grep -q -- "${pattern}" "${log_file}"; then
    return 0
  fi
  echo "[assert-fail] ${sid}: missing pattern '${pattern}'"
  return 1
}

assert_log_not_contains() {
  local sid="$1"
  local pattern="$2"
  local log_file="${LOG_DIR}/${sid}.log"
  if grep -q -- "${pattern}" "${log_file}"; then
    echo "[assert-fail] ${sid}: unexpected pattern '${pattern}'"
    return 1
  fi
  return 0
}

assert_path_exists() {
  local sid="$1"
  local p="$2"
  if [[ -e "${p}" ]]; then
    return 0
  fi
  echo "[assert-fail] ${sid}: path not found ${p}"
  return 1
}

assert_path_not_exists() {
  local sid="$1"
  local p="$2"
  if [[ ! -e "${p}" ]]; then
    return 0
  fi
  echo "[assert-fail] ${sid}: path should not exist ${p}"
  return 1
}

make_bad_supported_versions_cfg() {
  local out="$1"
  python3 - "$BASE_CFG" "$out" <<'PY'
import sys
from pathlib import Path
import yaml

base = Path(sys.argv[1])
out = Path(sys.argv[2])
raw = yaml.safe_load(base.read_text(encoding="utf-8"))
for item in raw.get("packages", []):
    if item.get("product") == "Porting-Advisor":
        item["version"] = "26.0.RC2"
        break
out.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
PY
}

make_bad_download_cfg() {
  local out="$1"
  python3 - "$BASE_CFG" "$out" <<'PY'
import sys
from pathlib import Path
import yaml

base = Path(sys.argv[1])
out = Path(sys.argv[2])
raw = yaml.safe_load(base.read_text(encoding="utf-8"))
raw["download_defaults"]["base_url"] = "https://127.0.0.1:9/not-exist"
out.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
PY
}

make_bad_verify_cfg() {
  local out="$1"
  python3 - "$BASE_CFG" "$out" <<'PY'
import sys
from pathlib import Path
import yaml

base = Path(sys.argv[1])
out = Path(sys.argv[2])
raw = yaml.safe_load(base.read_text(encoding="utf-8"))
raw["verify_defaults"]["signature_format"] = "PEM"
out.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
PY
}

make_devkit_bad_install_dir_cfg() {
  local out="$1"
  python3 - "$BASE_CFG" "$out" <<'PY'
import sys
from pathlib import Path
import yaml

base = Path(sys.argv[1])
out = Path(sys.argv[2])
raw = yaml.safe_load(base.read_text(encoding="utf-8"))
for item in raw.get("packages", []):
    if item.get("product") == "devkit-porting":
        item["install_dir"] = "_internal/porting_cli_file"
        break
out.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
PY
}

write_state() {
  local path="$1"
  local product="$2"
  local version="$3"
  local package_id="$4"
  local package_format="$5"
  python3 - "$path" "$product" "$version" "$package_id" "$package_format" <<'PY'
import sys
from pathlib import Path
import yaml

path = Path(sys.argv[1])
product = sys.argv[2]
version = sys.argv[3]
package_id = sys.argv[4]
package_format = sys.argv[5]
state = {
    "products": {
        product: {
            "installed_version": version,
            "installed_at": "2026-05-09T00:00:00+08:00",
            "package_id": package_id,
            "package_format": package_format,
            "last_result": "success",
        }
    }
}
path.write_text(yaml.safe_dump(state, sort_keys=False, allow_unicode=False), encoding="utf-8")
PY
}

cleanup_runtime() {
  rm -rf "${PORTING_DIR}" "${PKG_ROOT}"
}

cleanup_runtime

# S01: Porting-Advisor pre_check 通过
rm -f "${STATE_PORTING}"
run_case "S01" 0 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${STATE_PORTING}" "${BIN_PATH}" --name Porting-Advisor
assert_log_contains "S01" "Installer run completed"

# S02: Porting-Advisor pre_check 不通过（跳过）
run_case "S02" 0 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${STATE_PORTING}" "${BIN_PATH}" --name Porting-Advisor
assert_log_contains "S02" "Installer pre-check hit, skip installation"

# S03: devkit-porting pre_check 通过
rm -f "${STATE_DEVKIT}"
run_case "S03" 0 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${STATE_DEVKIT}" "${BIN_PATH}" --name devkit-porting
assert_log_contains "S03" "Installer run completed"

# S04: devkit-porting pre_check 不通过（跳过）
run_case "S04" 0 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${STATE_DEVKIT}" "${BIN_PATH}" --name devkit-porting
assert_log_contains "S04" "Installer pre-check hit, skip installation"

# S05: version 不在 supported_versions
BAD_SV_CFG="${LOG_DIR}/bad_supported_versions.yaml"
make_bad_supported_versions_cfg "${BAD_SV_CFG}"
run_case "S05" 10 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_SV_CFG}" "${BIN_PATH}" --list-packages
assert_log_contains "S05" "not in supported_versions"

# S06: 已安装版本低于目标版本（触发切换）
write_state "${LOG_DIR}/state_s06.yaml" "Porting-Advisor" "25.0.RC1" "${PORTING_ID}" "tar.gz"
run_case "S06" 0 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${LOG_DIR}/state_s06.yaml" "${BIN_PATH}" --name Porting-Advisor
assert_log_contains "S06" "Detected version switch for Porting-Advisor: 25.0.RC1 -> 26.0.RC1"

# S07: 已安装版本高于目标版本（触发切换）
write_state "${LOG_DIR}/state_s07.yaml" "Porting-Advisor" "99.0.RC1" "${PORTING_ID}" "tar.gz"
run_case "S07" 0 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${LOG_DIR}/state_s07.yaml" "${BIN_PATH}" --name Porting-Advisor
assert_log_contains "S07" "Detected version switch for Porting-Advisor: 99.0.RC1 -> 26.0.RC1"

# S08: Porting-Advisor 安装结果必须包含 config/jre/sql-analysis jar
assert_path_exists "S08" "${PORTING_DIR}/config"
assert_path_exists "S08" "${PORTING_DIR}/jre"
if ls "${PORTING_DIR}"/sql-analysis-*.jar >/dev/null 2>&1; then
  :
else
  echo "[assert-fail] S08: missing sql-analysis-*.jar under ${PORTING_DIR}"
  exit 1
fi

# S09: 成功后下载临时目录应清空
assert_path_not_exists "S09" "${PORTING_PKG_DIR}"
assert_path_not_exists "S09" "${DEVKIT_PKG_DIR}"

# S10: --name 与 --package-id 冲突
run_case "S10" 10 "${BIN_PATH}" --name Porting-Advisor --package-id "${PORTING_ID}"
assert_log_contains "S10" "Use either name or package-id"

# S11: install_state YAML 损坏
printf '{bad-yaml' > "${LOG_DIR}/bad_state.yaml"
run_case "S11" 10 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${LOG_DIR}/bad_state.yaml" "${BIN_PATH}" --name Porting-Advisor
assert_log_contains "S11" "Failed to parse install state YAML"

# S12: config YAML 损坏
printf 'download_defaults: [\n' > "${LOG_DIR}/bad_config.yaml"
run_case "S12" 10 env PACKAGE_MANAGER_CONFIG_FILE="${LOG_DIR}/bad_config.yaml" "${BIN_PATH}" --list-packages
assert_log_contains "S12" "Failed to parse YAML config"

# S13: 下载地址不可达
BAD_DL_CFG="${LOG_DIR}/bad_download.yaml"
make_bad_download_cfg "${BAD_DL_CFG}"
run_case "S13" 20 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_DL_CFG}" "${BIN_PATH}" --name Porting-Advisor
assert_log_contains "S13" "Failed to download"

# S14: 验签失败（错误 signature_format）
BAD_VERIFY_CFG="${LOG_DIR}/bad_verify.yaml"
make_bad_verify_cfg "${BAD_VERIFY_CFG}"
run_case "S14" 40 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_VERIFY_CFG}" "${BIN_PATH}" --name Porting-Advisor
assert_log_contains "S14" "P7S verification failed"

# S15: 伪造不支持架构
FAKE_BIN_DIR="${LOG_DIR}/fake_bin"
mkdir -p "${FAKE_BIN_DIR}"
cat > "${FAKE_BIN_DIR}/uname" <<'FAKE'
#!/usr/bin/env bash
if [[ "${1:-}" == "-m" ]]; then
  echo "riscv64"
  exit 0
fi
exec /usr/bin/uname "$@"
FAKE
chmod +x "${FAKE_BIN_DIR}/uname"
run_case "S15" 10 env PATH="${FAKE_BIN_DIR}:${PATH}" "${BIN_PATH}" --list-packages
assert_log_contains "S15" "Unsupported runtime architecture"

# S16: 同版本记录但安装目录缺失 -> 应重新安装，不应 skip
write_state "${LOG_DIR}/state_s16.yaml" "Porting-Advisor" "26.0.RC1" "${PORTING_ID}" "tar.gz"
rm -rf "${PORTING_DIR}"
run_case "S16" 0 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${LOG_DIR}/state_s16.yaml" "${BIN_PATH}" --name Porting-Advisor
assert_log_not_contains "S16" "Installer pre-check hit, skip installation"
assert_log_contains "S16" "Installer run completed"

# S18: devkit-porting 安装目录整理失败（install_dir 指向已存在文件）
BAD_DEVKIT_CFG="${LOG_DIR}/bad_devkit_install_dir.yaml"
make_devkit_bad_install_dir_cfg "${BAD_DEVKIT_CFG}"
: > "${DIST_DIR}/_internal/porting_cli_file"
write_state "${LOG_DIR}/state_s18.yaml" "devkit-porting" "25.0.rc1-1" "${DEVKIT_ID}" "rpm"
run_case "S18" 50 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_DEVKIT_CFG}" PACKAGE_MANAGER_INSTALL_STATE_FILE="${LOG_DIR}/state_s18.yaml" "${BIN_PATH}" --name devkit-porting
assert_log_contains "S18" "Failed to prepare porting root directory"
rm -f "${DIST_DIR}/_internal/porting_cli_file"

# S19: 根证书缺失（verify_chain=true）
if [[ -f "${OPENSSL_PEM}" ]]; then
  mv "${OPENSSL_PEM}" "${OPENSSL_PEM}.bak"
fi
run_case "S19" 40 "${BIN_PATH}" --name Porting-Advisor
assert_log_contains "S19" "Root CA file does not exist"
if [[ -f "${OPENSSL_PEM}.bak" ]]; then
  mv "${OPENSSL_PEM}.bak" "${OPENSSL_PEM}"
fi

# S20: 清理失败路径（包目录被文件占位，触发 cleanup_temp failed）
rm -rf "${PKG_ROOT}"
mkdir -p "${PKG_ROOT}"
: > "${PORTING_PKG_DIR}"
run_case "S20" 50 "${BIN_PATH}" --name Porting-Advisor
assert_log_contains "S20" "cleanup temp failed"
assert_log_contains "S20" "Unhandled installer exception"

# 汇总
SUMMARY_FILE="${LOG_DIR}/summary.txt"
{
  echo "run_id=${RUN_ID}"
  echo "total=${TOTAL}"
  echo "passed=${PASSED}"
  echo "failed=${FAILED}"
  echo "log_dir=${LOG_DIR}"
  for rc_path in "${LOG_DIR}"/*.rc; do
    sid="$(basename "${rc_path}" .rc)"
    rc="$(cat "${rc_path}")"
    echo "${sid}=${rc}"
  done | sort
} > "${SUMMARY_FILE}"

cat "${SUMMARY_FILE}"

echo "\n场景执行完成（已跳过 S17）"
