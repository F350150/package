#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# e2e_cases.sh
#
# 目标：执行 package-manager 端到端场景回归（按场景编号）
# 默认覆盖：S01-S16, S18-S20 + 离线新特性分支场景 S21-S29（显式跳过 S17）
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

PORTING_PRODUCT="DevKit-Porting-Advisor"
DEVKIT_PRODUCT="devkit-porting"
PORTING_DIR="${DIST_DIR}/_internal/porting_cli"
PKG_ROOT="${DIST_DIR}/_internal/packages"
PORTING_PKG_DIR="${PKG_ROOT}/${PORTING_PRODUCT}"
DEVKIT_PKG_DIR="${PKG_ROOT}/${DEVKIT_PRODUCT}"

STATE_PORTING="${LOG_DIR}/state_porting.yaml"
STATE_DEVKIT="${LOG_DIR}/state_devkit.yaml"

TOTAL=0
PASSED=0
FAILED=0

case_desc() {
  local sid="$1"
  case "${sid}" in
    S01) echo "Porting-Advisor 首次安装（pre_check 通过）" ;;
    S02) echo "Porting-Advisor 同版本二次安装（pre_check 跳过）" ;;
    S03) echo "devkit-porting 首次安装（主包+framework 全链路）" ;;
    S04) echo "devkit-porting 同版本二次安装（pre_check 跳过）" ;;
    S05) echo "项目版本不在 supported_versions（配置拒绝）" ;;
    S06) echo "低版本 -> 目标版本（触发版本切换重装）" ;;
    S07) echo "高版本 -> 目标版本（触发版本切换重装）" ;;
    S08) echo "Porting-Advisor 产物目录包含 config/jre/sql-analysis-*.jar" ;;
    S09) echo "安装成功后下载缓存目录被清理" ;;
    S10) echo "CLI 不支持 --package-id 参数" ;;
    S11) echo "install_state YAML 损坏时受控报错" ;;
    S12) echo "config YAML 损坏时受控报错" ;;
    S13) echo "下载不可达时报错 + 离线提示" ;;
    S14) echo "验签失败分支（错误 signature_format 注入）" ;;
    S15) echo "不支持架构分支（伪造 uname -m）" ;;
    S16) echo "同版本记录但安装目录缺失，必须重装" ;;
    S18) echo "devkit-porting 目录整理失败分支" ;;
    S19) echo "根证书缺失分支（verify_chain=true）" ;;
    S20) echo "清理失败分支（主错误不被覆盖）" ;;
    S21) echo "PA 本地包+签名命中，网络不可达仍可安装" ;;
    S22) echo "PA 主包命中、签名缺失，网络可达补齐后安装" ;;
    S23) echo "PA 主包空文件 + 网络不可达 -> 离线提示" ;;
    S24) echo "PA 主包缺失 + 网络不可达 -> 离线提示" ;;
    S25) echo "DP 四文件本地命中，网络不可达仍可安装" ;;
    S26) echo "DP framework 主包缺失，网络可达补齐后安装" ;;
    S27) echo "DP framework 主包缺失 + 网络不可达 -> 离线提示" ;;
    S28) echo "DP framework 主包空文件 + 网络不可达 -> 离线提示" ;;
    S29) echo "DP framework 签名缺失 + 网络不可达 -> 离线提示" ;;
    *) echo "未命名场景" ;;
  esac
}

case_pass_rule() {
  local sid="$1"
  case "${sid}" in
    S01|S03|S06|S07|S16|S21|S22|S25|S26) echo "返回码=0，且日志出现 'Installer run completed'" ;;
    S02|S04) echo "返回码=0，且日志出现 'Installer pre-check hit, skip installation'" ;;
    S05) echo "返回码=10，且日志出现 'not in supported_versions'" ;;
    S08) echo "目标目录存在 config/jre/sql-analysis-*.jar" ;;
    S09) echo "下载缓存目录不存在（已清理）" ;;
    S10) echo "返回码=2，且日志出现 unrecognized arguments: --package-id" ;;
    S11) echo "返回码=10，且日志出现 install_state YAML 解析失败" ;;
    S12) echo "返回码=10，且日志出现 config YAML 解析失败" ;;
    S13|S23|S24|S27|S28|S29) echo "返回码=20，且日志包含 'Offline install hint' 与目标路径" ;;
    S14|S19) echo "返回码=40，且日志出现验签/证书错误关键字" ;;
    S15) echo "返回码=10，且日志出现 Unsupported runtime architecture" ;;
    S18|S20) echo "返回码=50，且日志出现安装/清理失败关键字" ;;
    *) echo "返回码与关键证据同时满足" ;;
  esac
}

print_case_separator() {
  local sid="$1"
  local phase="$2"
  local desc
  desc="$(case_desc "${sid}")"
  echo
  echo "============================================================"
  echo "[${phase}] CASE ${sid} | ${desc}"
  echo "============================================================"
}

print_case_key_output() {
  local sid="$1"
  local expected_rc="$2"
  local rc="$3"
  local log_file="${LOG_DIR}/${sid}.log"

  echo "-------------------- CASE META -----------------------------"
  echo "case=${sid} expected_rc=${expected_rc} actual_rc=${rc}"
  echo "desc=$(case_desc "${sid}")"
  echo "pass_rule=$(case_pass_rule "${sid}")"
  echo "log=${log_file}"
  echo "------------------- KEY OUTPUT -----------------------------"

  if [[ -s "${log_file}" ]]; then
    # 关键链路输出：安装流程、下载/离线分支、验签、错误与回滚。
    grep -E \
      "Installer run started|Detected version switch|Installer pre-check hit|package_url=|signature_url=|Use local artifact file|Downloading |Remote file size|verify_chain=|OpenSSL return code|OpenSSL stderr|Installer run completed|Installer run failed|Installer error|Offline install hint|rollback completed|rollback failed|cleanup temp completed|cleanup temp failed|WARNING:" \
      "${log_file}" || true
  else
    echo "(empty log)"
  fi

  echo "--------------------- LOG TAIL -----------------------------"
  tail -n 8 "${log_file}" 2>/dev/null || true
  echo "------------------------------------------------------------"
}

run_case() {
  local sid="$1"
  local expected_rc="$2"
  shift 2
  local log_file="${LOG_DIR}/${sid}.log"
  local rc_file="${LOG_DIR}/${sid}.rc"
  local rc

  TOTAL=$((TOTAL + 1))
  print_case_separator "${sid}" "RUN"
  set +e
  "$@" >"${log_file}" 2>&1
  rc=$?
  set -e
  echo "${rc}" >"${rc_file}"
  print_case_key_output "${sid}" "${expected_rc}" "${rc}"

  if [[ "${rc}" == "${expected_rc}" ]]; then
    PASSED=$((PASSED + 1))
    echo "[pass] ${sid} 返回码符合预期: ${rc}"
    echo "[pass-criteria] $(case_pass_rule "${sid}")"
    print_case_separator "${sid}" "PASS"
    return 0
  fi

  FAILED=$((FAILED + 1))
  echo "[fail] ${sid} rc=${rc} expected=${expected_rc}"
  echo "------------------- FULL LOG START -------------------------"
  cat "${log_file}" || true
  echo "-------------------- FULL LOG END --------------------------"
  print_case_separator "${sid}" "FAIL"
  return 1
}

assert_log_contains() {
  local sid="$1"
  local pattern="$2"
  local log_file="${LOG_DIR}/${sid}.log"
  if grep -q -- "${pattern}" "${log_file}"; then
    local evidence
    evidence="$(grep -n -m 2 -- "${pattern}" "${log_file}" | head -n 2 | tr '\n' '; ')"
    echo "[evidence][${sid}] 命中 '${pattern}' -> ${evidence}"
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
  echo "[evidence][${sid}] 未出现不应存在关键字 '${pattern}'"
  return 0
}

assert_path_exists() {
  local sid="$1"
  local p="$2"
  if [[ -e "${p}" ]]; then
    echo "[evidence][${sid}] 路径存在: ${p}"
    return 0
  fi
  echo "[assert-fail] ${sid}: path not found ${p}"
  return 1
}

assert_path_not_exists() {
  local sid="$1"
  local p="$2"
  if [[ ! -e "${p}" ]]; then
    echo "[evidence][${sid}] 路径不存在（符合预期）: ${p}"
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
    if item.get("product") == "DevKit-Porting-Advisor":
        if "project_version" in item:
            item["project_version"] = "26.0.RC2"
        else:
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

resolve_product_meta() {
  local product="$1"
  local prefix="$2"
  PYTHONPATH="${ROOT_DIR}/src" python3 - "$BASE_CFG" "$PKG_ROOT" "$product" "$prefix" <<'PY'
import os
import shlex
import sys
from pathlib import Path

from package_manager.config import get_runtime_config
from package_manager.resolver import resolve_package, build_project_base_url

cfg_path = Path(sys.argv[1])
pkg_root = Path(sys.argv[2])
target_product = sys.argv[3]
prefix = sys.argv[4]

os.environ["PACKAGE_MANAGER_CONFIG_FILE"] = str(cfg_path)
runtime = get_runtime_config(reload=True)
dd = runtime.download_defaults
pc = None
for one in runtime.packages:
    if one.product == target_product and one.enabled:
        pc = one
        break
if pc is None:
    raise SystemExit(f"product not found: {target_product}")
resolved = resolve_package(pc, dd)

def emit(k, v):
    print(f"{prefix}{k}={shlex.quote(str(v))}")

emit("PACKAGE_URL", resolved.package_url)
emit("SIGNATURE_URL", resolved.signature_url)
emit("PACKAGE_PATH", pkg_root / resolved.config.product / resolved.filename)
emit("SIGNATURE_PATH", pkg_root / resolved.config.product / f"{resolved.filename}{dd.signature_suffix}")

if target_product == "devkit-porting":
    framework_filename = resolved.filename.replace("devkit-porting-", "devkit-", 1)
    project_base = build_project_base_url(dd.base_url, pc.version)
    framework_url = f"{project_base}/{framework_filename}"
    framework_sig_url = f"{framework_url}{dd.signature_suffix}"
    framework_pkg_path = pkg_root / resolved.config.product / framework_filename
    framework_sig_path = pkg_root / resolved.config.product / f"{framework_filename}{dd.signature_suffix}"
    emit("FRAMEWORK_URL", framework_url)
    emit("FRAMEWORK_SIGNATURE_URL", framework_sig_url)
    emit("FRAMEWORK_PATH", framework_pkg_path)
    emit("FRAMEWORK_SIGNATURE_PATH", framework_sig_path)
PY
}

fetch_to_seed() {
  local url="$1"
  local dst="$2"
  python3 - "$url" "$dst" <<'PY'
import ssl
import sys
import urllib.request
from pathlib import Path

url = sys.argv[1]
dst = Path(sys.argv[2])
dst.parent.mkdir(parents=True, exist_ok=True)
if dst.exists() and dst.stat().st_size > 0:
    raise SystemExit(0)
ctx = ssl.create_default_context()
with urllib.request.urlopen(url, timeout=300, context=ctx) as resp:
    data = resp.read()
if not data:
    raise SystemExit(f"empty data from {url}")
dst.write_bytes(data)
PY
}

copy_seed_file() {
  local src="$1"
  local dst="$2"
  mkdir -p "$(dirname "$dst")"
  cp -f "$src" "$dst"
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
  local package_format="$4"
  python3 - "$path" "$product" "$version" "$package_format" <<'PY'
import sys
from pathlib import Path
import yaml

path = Path(sys.argv[1])
product = sys.argv[2]
version = sys.argv[3]
package_format = sys.argv[4]
state = {
    "products": {
        product: {
            "installed_version": version,
            "installed_at": "2026-05-09T00:00:00+08:00",
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

# 离线场景预备：解析真实 URL 与目标路径，并一次性下载种子文件
eval "$(resolve_product_meta "DevKit-Porting-Advisor" "PA_")"
eval "$(resolve_product_meta "devkit-porting" "DP_")"
SEED_DIR="${LOG_DIR}/offline_seed"
mkdir -p "${SEED_DIR}"
fetch_to_seed "${PA_PACKAGE_URL}" "${SEED_DIR}/$(basename "${PA_PACKAGE_PATH}")"
fetch_to_seed "${PA_SIGNATURE_URL}" "${SEED_DIR}/$(basename "${PA_SIGNATURE_PATH}")"
fetch_to_seed "${DP_PACKAGE_URL}" "${SEED_DIR}/$(basename "${DP_PACKAGE_PATH}")"
fetch_to_seed "${DP_SIGNATURE_URL}" "${SEED_DIR}/$(basename "${DP_SIGNATURE_PATH}")"
fetch_to_seed "${DP_FRAMEWORK_URL}" "${SEED_DIR}/$(basename "${DP_FRAMEWORK_PATH}")"
fetch_to_seed "${DP_FRAMEWORK_SIGNATURE_URL}" "${SEED_DIR}/$(basename "${DP_FRAMEWORK_SIGNATURE_PATH}")"

# S01: Porting-Advisor pre_check 通过
rm -f "${STATE_PORTING}"
run_case "S01" 0 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${STATE_PORTING}" "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S01" "Installer run completed"

# S02: Porting-Advisor pre_check 不通过（跳过）
run_case "S02" 0 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${STATE_PORTING}" "${BIN_PATH}" --name DevKit-Porting-Advisor
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
run_case "S05" 10 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_SV_CFG}" "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S05" "not in supported_versions"

# S06: 已安装版本低于目标版本（触发切换）
write_state "${LOG_DIR}/state_s06.yaml" "DevKit-Porting-Advisor" "25.0.RC1" "tar.gz"
run_case "S06" 0 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${LOG_DIR}/state_s06.yaml" "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S06" "Detected version switch for DevKit-Porting-Advisor: 25.0.RC1 -> 26.0.RC1"

# S07: 已安装版本高于目标版本（触发切换）
write_state "${LOG_DIR}/state_s07.yaml" "DevKit-Porting-Advisor" "99.0.RC1" "tar.gz"
run_case "S07" 0 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${LOG_DIR}/state_s07.yaml" "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S07" "Detected version switch for DevKit-Porting-Advisor: 99.0.RC1 -> 26.0.RC1"

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

# S10: 传入不支持的 --package-id 参数
run_case "S10" 2 "${BIN_PATH}" --name DevKit-Porting-Advisor --package-id "${PORTING_PRODUCT}"
assert_log_contains "S10" "unrecognized arguments: --package-id"

# S11: install_state YAML 损坏
printf '{bad-yaml' > "${LOG_DIR}/bad_state.yaml"
run_case "S11" 10 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${LOG_DIR}/bad_state.yaml" "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S11" "Failed to parse install state YAML"

# S12: config YAML 损坏
printf 'download_defaults: [\n' > "${LOG_DIR}/bad_config.yaml"
run_case "S12" 10 env PACKAGE_MANAGER_CONFIG_FILE="${LOG_DIR}/bad_config.yaml" "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S12" "Failed to parse YAML config"

# S13: 下载地址不可达
BAD_DL_CFG="${LOG_DIR}/bad_download.yaml"
make_bad_download_cfg "${BAD_DL_CFG}"
run_case "S13" 20 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_DL_CFG}" "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S13" "Failed to download"
assert_log_contains "S13" "Offline install hint"

# S14: 验签失败（错误 signature_format）
BAD_VERIFY_CFG="${LOG_DIR}/bad_verify.yaml"
make_bad_verify_cfg "${BAD_VERIFY_CFG}"
run_case "S14" 40 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_VERIFY_CFG}" "${BIN_PATH}" --name DevKit-Porting-Advisor
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
run_case "S15" 10 env PATH="${FAKE_BIN_DIR}:${PATH}" "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S15" "Unsupported runtime architecture"

# S16: 同版本记录但安装目录缺失 -> 应重新安装，不应 skip
write_state "${LOG_DIR}/state_s16.yaml" "DevKit-Porting-Advisor" "26.0.RC1" "tar.gz"
rm -rf "${PORTING_DIR}"
run_case "S16" 0 env PACKAGE_MANAGER_INSTALL_STATE_FILE="${LOG_DIR}/state_s16.yaml" "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_not_contains "S16" "Installer pre-check hit, skip installation"
assert_log_contains "S16" "Installer run completed"

# S18: devkit-porting 安装目录整理失败（install_dir 指向已存在文件）
BAD_DEVKIT_CFG="${LOG_DIR}/bad_devkit_install_dir.yaml"
make_devkit_bad_install_dir_cfg "${BAD_DEVKIT_CFG}"
: > "${DIST_DIR}/_internal/porting_cli_file"
write_state "${LOG_DIR}/state_s18.yaml" "devkit-porting" "25.0.rc1-1" "rpm"
run_case "S18" 50 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_DEVKIT_CFG}" PACKAGE_MANAGER_INSTALL_STATE_FILE="${LOG_DIR}/state_s18.yaml" "${BIN_PATH}" --name devkit-porting
assert_log_contains "S18" "Failed to prepare porting root directory"
rm -f "${DIST_DIR}/_internal/porting_cli_file"

# S19: 根证书缺失（verify_chain=true）
if [[ -f "${OPENSSL_PEM}" ]]; then
  mv "${OPENSSL_PEM}" "${OPENSSL_PEM}.bak"
fi
run_case "S19" 40 "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S19" "Root CA file does not exist"
if [[ -f "${OPENSSL_PEM}.bak" ]]; then
  mv "${OPENSSL_PEM}.bak" "${OPENSSL_PEM}"
fi

# S20: 清理失败路径（包目录被文件占位，触发 cleanup_temp failed）
rm -rf "${PKG_ROOT}"
mkdir -p "${PKG_ROOT}"
: > "${PORTING_PKG_DIR}"
run_case "S20" 50 "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S20" "cleanup temp failed"
assert_log_contains "S20" "Unhandled installer exception"

# S21: Porting-Advisor 本地包+签名命中，网络不可达仍可安装
cleanup_runtime
copy_seed_file "${SEED_DIR}/$(basename "${PA_PACKAGE_PATH}")" "${PA_PACKAGE_PATH}"
copy_seed_file "${SEED_DIR}/$(basename "${PA_SIGNATURE_PATH}")" "${PA_SIGNATURE_PATH}"
run_case "S21" 0 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_DL_CFG}" "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S21" "Use local artifact file: ${PA_PACKAGE_PATH}"
assert_log_contains "S21" "Use local artifact file: ${PA_SIGNATURE_PATH}"

# S22: Porting-Advisor 仅主包命中，签名缺失可在线补齐后安装
cleanup_runtime
copy_seed_file "${SEED_DIR}/$(basename "${PA_PACKAGE_PATH}")" "${PA_PACKAGE_PATH}"
run_case "S22" 0 "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S22" "Use local artifact file: ${PA_PACKAGE_PATH}"
assert_log_contains "S22" "Downloading ${PA_SIGNATURE_URL}"

# S23: Porting-Advisor 本地主包为空文件，网络不可达 -> 离线提示
cleanup_runtime
mkdir -p "$(dirname "${PA_PACKAGE_PATH}")"
: > "${PA_PACKAGE_PATH}"
run_case "S23" 20 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_DL_CFG}" "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S23" "Offline install hint"
assert_log_contains "S23" "${PA_PACKAGE_PATH}"

# S24: Porting-Advisor 主包缺失且网络不可达 -> 离线提示
cleanup_runtime
run_case "S24" 20 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_DL_CFG}" "${BIN_PATH}" --name DevKit-Porting-Advisor
assert_log_contains "S24" "Offline install hint"
assert_log_contains "S24" "${PA_PACKAGE_PATH}"

# S25: devkit-porting 四个文件全本地命中，网络不可达仍可安装
cleanup_runtime
copy_seed_file "${SEED_DIR}/$(basename "${DP_PACKAGE_PATH}")" "${DP_PACKAGE_PATH}"
copy_seed_file "${SEED_DIR}/$(basename "${DP_SIGNATURE_PATH}")" "${DP_SIGNATURE_PATH}"
copy_seed_file "${SEED_DIR}/$(basename "${DP_FRAMEWORK_PATH}")" "${DP_FRAMEWORK_PATH}"
copy_seed_file "${SEED_DIR}/$(basename "${DP_FRAMEWORK_SIGNATURE_PATH}")" "${DP_FRAMEWORK_SIGNATURE_PATH}"
run_case "S25" 0 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_DL_CFG}" "${BIN_PATH}" --name devkit-porting
assert_log_contains "S25" "Use local artifact file: ${DP_PACKAGE_PATH}"
assert_log_contains "S25" "Use local artifact file: ${DP_SIGNATURE_PATH}"
assert_log_contains "S25" "Use local artifact file: ${DP_FRAMEWORK_PATH}"
assert_log_contains "S25" "Use local artifact file: ${DP_FRAMEWORK_SIGNATURE_PATH}"

# S26: devkit-porting framework 主包缺失，网络可达可补齐并安装
cleanup_runtime
copy_seed_file "${SEED_DIR}/$(basename "${DP_PACKAGE_PATH}")" "${DP_PACKAGE_PATH}"
copy_seed_file "${SEED_DIR}/$(basename "${DP_SIGNATURE_PATH}")" "${DP_SIGNATURE_PATH}"
copy_seed_file "${SEED_DIR}/$(basename "${DP_FRAMEWORK_SIGNATURE_PATH}")" "${DP_FRAMEWORK_SIGNATURE_PATH}"
run_case "S26" 0 "${BIN_PATH}" --name devkit-porting
assert_log_contains "S26" "Use local artifact file: ${DP_PACKAGE_PATH}"
assert_log_contains "S26" "Downloading ${DP_FRAMEWORK_URL}"

# S27: devkit-porting framework 主包缺失且网络不可达 -> 离线提示
cleanup_runtime
copy_seed_file "${SEED_DIR}/$(basename "${DP_PACKAGE_PATH}")" "${DP_PACKAGE_PATH}"
copy_seed_file "${SEED_DIR}/$(basename "${DP_SIGNATURE_PATH}")" "${DP_SIGNATURE_PATH}"
copy_seed_file "${SEED_DIR}/$(basename "${DP_FRAMEWORK_SIGNATURE_PATH}")" "${DP_FRAMEWORK_SIGNATURE_PATH}"
run_case "S27" 20 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_DL_CFG}" "${BIN_PATH}" --name devkit-porting
assert_log_contains "S27" "Offline install hint"
assert_log_contains "S27" "${DP_FRAMEWORK_PATH}"

# S28: devkit-porting framework 主包为空文件且网络不可达 -> 离线提示
cleanup_runtime
copy_seed_file "${SEED_DIR}/$(basename "${DP_PACKAGE_PATH}")" "${DP_PACKAGE_PATH}"
copy_seed_file "${SEED_DIR}/$(basename "${DP_SIGNATURE_PATH}")" "${DP_SIGNATURE_PATH}"
copy_seed_file "${SEED_DIR}/$(basename "${DP_FRAMEWORK_SIGNATURE_PATH}")" "${DP_FRAMEWORK_SIGNATURE_PATH}"
mkdir -p "$(dirname "${DP_FRAMEWORK_PATH}")"
: > "${DP_FRAMEWORK_PATH}"
run_case "S28" 20 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_DL_CFG}" "${BIN_PATH}" --name devkit-porting
assert_log_contains "S28" "Offline install hint"
assert_log_contains "S28" "${DP_FRAMEWORK_PATH}"

# S29: devkit-porting framework 签名缺失且网络不可达 -> 离线提示
cleanup_runtime
copy_seed_file "${SEED_DIR}/$(basename "${DP_PACKAGE_PATH}")" "${DP_PACKAGE_PATH}"
copy_seed_file "${SEED_DIR}/$(basename "${DP_SIGNATURE_PATH}")" "${DP_SIGNATURE_PATH}"
copy_seed_file "${SEED_DIR}/$(basename "${DP_FRAMEWORK_PATH}")" "${DP_FRAMEWORK_PATH}"
run_case "S29" 20 env PACKAGE_MANAGER_CONFIG_FILE="${BAD_DL_CFG}" "${BIN_PATH}" --name devkit-porting
assert_log_contains "S29" "Offline install hint"
assert_log_contains "S29" "${DP_FRAMEWORK_SIGNATURE_PATH}"

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

echo
echo "============================================================"
echo "[E2E DONE] 场景执行完成（已跳过 S17）"
echo "============================================================"
