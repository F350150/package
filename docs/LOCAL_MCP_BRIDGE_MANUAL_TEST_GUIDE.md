# Local MCP Bridge 手动测试指南（逐步验收版）

本文档用于在“远端 Python/mcp 环境受限”时，采用 Local MCP Bridge 方案完成全链路手工验收。

适用日期：2026-05-18

---

## 1. 目标与验收口径

你要验证的是这条链路真实可用：

1. 本地 `opencode` 能调用 MCP 工具。
2. 本地 MCP Server（bridge）能把安装动作转发到远端（容器/主机）。
3. 远端包管理状态能被正确读取与更新。

最终通过标准：

1. 安装自然语言请求先触发 `pm_probe_network`。
2. 根据 `recommended_mode` 自动分支（online/offline）。
3. offline 分支会先完成离线制品投放，再安装。
4. 最终 `pm_status` 返回目标产品已安装且 `last_result=success`。

---

## 2. 测试拓扑

- 本地：`opencode` + `package_manager.mcp_server`（127.0.0.1:18880）。
- 远端：`openeuler-arm-mcp` 容器（或你的远端主机）执行 `package-manager` 二进制。
- Bridge：本地 wrapper 脚本，通过 `docker exec`（或 `ssh`）把命令转发到远端。

---

## 3. 前置检查（必须先通过）

### 步骤 3.1：检查本地工具
执行：
```bash
opencode --version
docker ps -a
python --version
```
预期：
1. `opencode` 有版本号。
2. 远端容器存在且 `Up`。
3. 本地 Python 可运行。

验证：
1. 看到容器名（示例：`openeuler-arm-mcp`）。

### 步骤 3.2：检查远端包管理产物
执行：
```bash
docker exec openeuler-arm-mcp /bin/sh -lc '
ls -la /opt/package-manager/current/package-manager &&
ls -la /opt/package-manager/current/config/packages.yaml &&
ls -la /opt/package-manager/current/.package-manager/.install_state.yaml
'
```
预期：
1. 三个路径都存在。

验证：
1. `ls` 输出均非 `No such file or directory`。

---

## 4. 准备 Bridge 工作目录

### 步骤 4.1：创建目录并同步远端配置/状态
执行：
```bash
mkdir -p /private/tmp/pm-mcp-bridge
docker cp openeuler-arm-mcp:/opt/package-manager/current/config/packages.yaml /private/tmp/pm-mcp-bridge/packages.yaml
docker cp openeuler-arm-mcp:/opt/package-manager/current/.package-manager/.install_state.yaml /private/tmp/pm-mcp-bridge/install_state.yaml
```
预期：
1. 本地出现 `packages.yaml`、`install_state.yaml`。

验证：
```bash
ls -la /private/tmp/pm-mcp-bridge
```

### 步骤 4.2：创建容器转发 wrapper
执行：
```bash
cat > /private/tmp/pm-mcp-bridge/pm-container-wrapper.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail

CONTAINER="openeuler-arm-mcp"
REMOTE_BIN="/opt/package-manager/current/package-manager"
REMOTE_STATE="/opt/package-manager/current/.package-manager/.install_state.yaml"
LOCAL_STATE="${PACKAGE_MANAGER_INSTALL_STATE_FILE:-/private/tmp/pm-mcp-bridge/install_state.yaml}"

sync_state() {
  docker cp "${CONTAINER}:${REMOTE_STATE}" "${LOCAL_STATE}" >/dev/null 2>&1 || true
}

if [[ "${1:-}" == "--help" ]]; then
  exec docker exec "${CONTAINER}" /bin/sh -lc "'${REMOTE_BIN}' --help"
fi

NAME=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      NAME="${2:-}"
      shift 2
      ;;
    --dry-run)
      shift
      ;;
    *)
      shift
      ;;
  esac
done

if [[ -z "${NAME}" ]]; then
  echo "missing --name" >&2
  exit 2
fi

docker exec "${CONTAINER}" /bin/sh -lc "'${REMOTE_BIN}' --name '${NAME}'"
rc=$?
sync_state
exit $rc
SH
chmod +x /private/tmp/pm-mcp-bridge/pm-container-wrapper.sh
```
预期：
1. 脚本可执行。

验证：
```bash
/private/tmp/pm-mcp-bridge/pm-container-wrapper.sh --help
```
期望输出含 `usage: package-manager ... --name NAME`。

---

## 5. 启动本地 MCP Bridge Server

### 步骤 5.1：启动
执行（在项目根目录）：
```bash
PYTHONPATH=/Users/fxl/pycharm_projects/package/src \
PACKAGE_MANAGER_MCP_DRY_RUN_MODE=simulate \
PACKAGE_MANAGER_INSTALL_LOCK_FILE=/private/tmp/pm-mcp-bridge/install.lock \
python -m package_manager.mcp_server \
  --host 127.0.0.1 \
  --port 18880 \
  --path /mcp \
  --binary-path /private/tmp/pm-mcp-bridge/pm-container-wrapper.sh \
  --config-file /private/tmp/pm-mcp-bridge/packages.yaml \
  --state-file /private/tmp/pm-mcp-bridge/install_state.yaml \
  --auth-disabled
```
预期：
1. 控制台出现 `Uvicorn running on http://127.0.0.1:18880`。

验证：
1. 该终端保持运行，不要关闭。

说明：
1. `dry_run_mode=simulate` 是为了兼容“不支持 `--dry-run` 的旧远端二进制”。
2. `install.lock` 放到 `/private/tmp`，避免本机权限问题。

---

## 6. 在 opencode 注册并连通 MCP

### 步骤 6.1：注册
执行：
```bash
opencode mcp add
```
输入建议：
1. `name`: `package-manager-remote`
2. `type`: `remote`
3. `url`: `http://127.0.0.1:18880/mcp`
4. `oauth`: `false`
5. `enabled`: `true`

### 步骤 6.2：检查连接
执行：
```bash
opencode mcp list
```
预期：
1. `package-manager-remote` 显示 `connected`。

验证：
1. 若是 `failed`，先检查第 5 步进程是否还在。

---

## 7. 工具级手动验收（推荐先做）

在 `opencode` 会话中逐条执行。

### 步骤 7.1：自动路由安装（主用例）
输入：
`安装 DevKit-Porting-Advisor，并返回每个阶段结果`

预期：
1. 首先调用 `pm_probe_network`。
2. online 分支：`pm_skill_install_guarded -> pm_status`。
3. offline 分支：`pm_offline_manifest -> 本地离线投放 -> pm_check_offline_artifacts -> pm_skill_install_guarded -> pm_status`。

验证点：
1. 第一阶段必须是网络探测。
2. 分支和 `recommended_mode` 一致。

### 步骤 7.2：健康检查
输入：
`检查远端包管理服务健康状态`

预期：
1. 调用 `pm_health`。
2. 返回健康（`healthy=true`）。

验证点：
1. `binary_exists=true`
2. `config_exists=true`
3. `state_parent_exists=true`

### 步骤 7.3：列包
输入：
`列出当前可安装产品`

预期：
1. 调用 `pm_list_packages`。
2. 返回产品列表。

验证点：
1. 包含 `DevKit-Porting-Advisor`。
2. `count >= 1`。

### 步骤 7.4：dry-run
输入：
`安装 DevKit-Porting-Advisor，先 dry-run`

预期：
1. 调用 `pm_install`（`dry_run=true`）或 `pm_skill_install_guarded` 内部 dry-run 阶段。
2. dry-run 返回 `status=success`。

验证点：
1. 返回中 `dry_run=true`。
2. `dry_run_mode=simulate`（当前方案）。

### 步骤 7.5：真实安装
输入：
`执行真实安装 DevKit-Porting-Advisor 并返回状态`

预期：
1. 调用真实安装（`dry_run=false`）。
2. 安装成功或同版本跳过。
3. 最终给出 `pm_status` 结果。

验证点：
1. `install.status=success`。
2. `status.state.installed_version` 存在。
3. `status.state.last_result=success`。

### 步骤 7.6：显式状态复核
输入：
`调用 pm_status 查看 DevKit-Porting-Advisor 当前状态`

预期：
1. 返回已安装状态。

验证点：
1. `installed_version` 与预期一致。
2. `last_result=success`。

---

## 8. 远端侧一致性验证（关键）

### 步骤 8.1：查看容器真实状态
执行：
```bash
docker exec openeuler-arm-mcp /bin/sh -lc '
cat /opt/package-manager/current/.package-manager/.install_state.yaml
'
```
预期：
1. 目标产品有记录。
2. `installed_version`、`last_result` 与 opencode 输出一致。

### 步骤 8.2：对比本地镜像状态
执行：
```bash
cat /private/tmp/pm-mcp-bridge/install_state.yaml
```
预期：
1. 与容器状态同步一致（wrapper 每次真实安装后会拉取状态）。

---

## 9. 负向测试（建议执行）

### 步骤 9.1：产品名错误
输入：
`安装 Not-Exist-Product，先 dry-run`

预期：
1. 返回 `unknown or disabled product`。
2. 输出可安装列表用于纠正。

### 步骤 9.2：停止 bridge 后再调工具
操作：
1. 停掉第 5 步 MCP 进程。
2. 再执行 `检查远端包管理服务健康状态`。

预期：
1. `opencode mcp list` 变为 `failed` 或会话中调用失败。

验证：
1. 能稳定复现“连接不可达”。

---

## 10. 常见问题与修复

1. `permission denied ... docker.sock`
- 现象：wrapper 不能执行 `docker exec`。
- 修复：在有 Docker 权限的环境执行，或使用提权方式运行。

2. `auth-disabled on non-loopback host is blocked`
- 现象：MCP 启动失败。
- 修复：bridge 模式请固定 `--host 127.0.0.1`。

3. `lock_timeout`
- 现象：安装返回锁超时。
- 修复：确认 `PACKAGE_MANAGER_INSTALL_LOCK_FILE` 在可写目录（推荐 `/private/tmp/...`）。

4. `command_exec_error`
- 现象：无法执行 wrapper 或远端 binary。
- 修复：检查 `--binary-path`、脚本执行位、容器内路径。

5. `No enabled package found`
- 现象：找不到产品。
- 修复：检查 `packages.yaml` 是否同步、目标产品是否 `enabled: true`。

---

## 11. 测试完成后的清理

1. 停止 bridge MCP 进程（Ctrl+C）。
2. 如需移除临时文件：
```bash
rm -rf /private/tmp/pm-mcp-bridge
```
3. 如不再需要该 MCP 连接，可在 `opencode` 中删除或禁用该条目。

---

## 12. 验收记录模板（建议复制使用）

- 执行日期：
- 测试人：
- 环境：`opencode version` / `docker image` / `container name`
- Step 7.1（auto-route）：通过/失败，证据：
- Step 7.2（health）：通过/失败，证据：
- Step 7.3（list）：通过/失败，证据：
- Step 7.4（dry-run）：通过/失败，证据：
- Step 7.5（real install）：通过/失败，证据：
- Step 7.6（status）：通过/失败，证据：
- Step 8（一致性验证）：通过/失败，证据：
- 结论：通过 / 不通过
