# package-manager 远端 MCP Server 操作指南（容器直连版）

本文档给出“远端容器直连 MCP”的完整落地与手工验收流程。

适用日期：2026-05-17

---

## 1. 方案选择

### 1.1 推荐主路径：Remote MCP Server（容器直连）
- 在远端容器内直接运行 `package_manager.mcp_server`。
- 本地 `opencode` 直接连远端容器暴露端口。
- 优点：链路清晰、可共享、后续更容易上生产。

### 1.2 兜底路径：Local MCP Bridge
- 当远端无法装 `mcp` 或运行时受限时使用。
- 详见：
  - [LOCAL_MCP_BRIDGE_MANUAL_TEST_GUIDE.md](/Users/fxl/pycharm_projects/package/docs/LOCAL_MCP_BRIDGE_MANUAL_TEST_GUIDE.md)

---

## 2. 目标链路

`opencode -> remote MCP server -> control_plane -> package-manager binary -> install_state`

验收通过标准：
1. `pm_health` 返回 `healthy=true`。
2. `pm_list_packages` 返回目标产品（如 `DevKit-Porting-Advisor`）。
3. `pm_install(dry_run=true)` 返回 `status=success`。
4. `pm_install(dry_run=false)` 返回 `status=success`（或同版本已安装跳过）。
5. `pm_status` 返回 `installed_version` 且 `last_result=success`。

---

## 3. 前置条件

### 3.1 容器与端口
1. 需要容器：`openeuler-arm-mcp`。
2. 需要端口映射：`18800:18800`。

检查：
```bash
docker ps -a | grep openeuler-arm-mcp
```

若容器未启动：
```bash
docker start openeuler-arm-mcp
```

若没有 `18800` 端口映射，建议重建容器：
```bash
docker rm -f openeuler-arm-mcp
docker run -d --name openeuler-arm-mcp -p 18800:18800 openeuler/openeuler:22.03-lts sleep infinity
```

### 3.2 远端产物检查
```bash
docker exec openeuler-arm-mcp /bin/sh -lc '
ls -la /opt/package-manager/current/package-manager &&
ls -la /opt/package-manager/current/config/packages.yaml &&
ls -la /opt/package-manager/current/.package-manager/.install_state.yaml
'
```

预期：三条 `ls` 均成功。

---

## 4. 在容器内安装 CPython 3.11（推荐）

> openEuler 22.03 默认 Python 3.9 常见无法安装 `mcp`，建议单独编译安装 Python 3.11，不覆盖系统 Python。

### 4.1 安装编译依赖
```bash
docker exec openeuler-arm-mcp /bin/sh -lc '
dnf -y install gcc make wget tar gzip bzip2-devel libffi-devel openssl-devel zlib-devel xz-devel readline-devel sqlite-devel gdbm-devel ncurses-devel tk-devel libuuid-devel patch findutils &&
dnf clean all
'
```

### 4.2 编译安装 CPython 3.11.11
```bash
docker exec openeuler-arm-mcp /bin/sh -lc '
set -euo pipefail
cd /tmp
PYVER=3.11.11
[ -f Python-${PYVER}.tgz ] || wget -q https://www.python.org/ftp/python/${PYVER}/Python-${PYVER}.tgz
rm -rf Python-${PYVER}
tar -xzf Python-${PYVER}.tgz
cd Python-${PYVER}
./configure --prefix=/opt/cpython-3.11 --with-ensurepip=install
make -j2
make altinstall
/opt/cpython-3.11/bin/python3.11 --version
/opt/cpython-3.11/bin/pip3.11 --version
'
```

预期：
1. Python 版本显示 `3.11.x`。
2. pip 正常。

### 4.3 安装 `mcp` 与项目包
```bash
docker exec openeuler-arm-mcp /bin/sh -lc '
/opt/cpython-3.11/bin/pip3.11 install -U pip
/opt/cpython-3.11/bin/pip3.11 install mcp
/opt/cpython-3.11/bin/pip3.11 install -e /opt/package-manager/source
/opt/cpython-3.11/bin/python3.11 - <<"PY"
import mcp
from package_manager import mcp_server
print("mcp ok", mcp.__file__)
print("package_manager.mcp_server ok")
PY
'
```

预期：
1. `mcp ok`。
2. `package_manager.mcp_server ok`。

---

## 5. 同步代码并启动远端 MCP Server（容器内）

> 推荐每次本地改完 `mcp_server.py` 或 `control_plane.py` 后，先同步再重启。

### 5.1 同步最新代码到容器
```bash
docker cp /Users/fxl/pycharm_projects/package/src/package_manager/control_plane.py \
  openeuler-arm-mcp:/opt/package-manager/source/src/package_manager/control_plane.py

docker cp /Users/fxl/pycharm_projects/package/src/package_manager/mcp_server.py \
  openeuler-arm-mcp:/opt/package-manager/source/src/package_manager/mcp_server.py
```

### 5.2 杀掉旧 MCP 进程
```bash
docker exec openeuler-arm-mcp /bin/sh -lc \
"pid=\$(ps -ef | grep -E '/opt/cpython-3.11/bin/python3.11 -m package_manager.mcp_server' | grep -v grep | awk '{print \$2}' | head -n1); [ -n \"\$pid\" ] && kill \$pid || true"
```

### 5.3 启动新 MCP 进程（静态 token + header 鉴权）
```bash
docker exec openeuler-arm-mcp /bin/sh -lc \
"nohup /opt/cpython-3.11/bin/python3.11 -m package_manager.mcp_server \
  --host 0.0.0.0 \
  --port 18800 \
  --path /mcp \
  --binary-path /opt/package-manager/current/package-manager \
  --config-file /opt/package-manager/current/config/packages.yaml \
  --state-file /opt/package-manager/current/.package-manager/.install_state.yaml \
  --token 'pm-demo-token-20260517' \
  --token-scopes 'pm:read,pm:write,pm:admin' \
  --public-base-url 'http://127.0.0.1:18800' \
  --stateless-http \
  >/tmp/mcp-server.log 2>&1 &"
```

### 5.4 检查进程和日志
```bash
docker exec openeuler-arm-mcp /bin/sh -lc \
"ps -ef | grep -E 'package_manager.mcp_server' | grep -v grep; tail -n 50 /tmp/mcp-server.log"
```

预期：
1. 能看到 `python3.11 -m package_manager.mcp_server` 进程。
2. 日志出现 `Uvicorn running on http://0.0.0.0:18800`。

---

## 6. 在 opencode 注册远端 MCP

推荐直接写项目级配置文件 `opencode.json`：
```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "package-manager-remote": {
      "type": "remote",
      "url": "http://127.0.0.1:18800/mcp",
      "headers": {
        "Authorization": "Bearer pm-demo-token-20260517"
      }
    }
  }
}
```

也可通过交互命令 `opencode mcp add` 添加，关键参数保持一致：
1. `name`: `package-manager-remote`
2. `type`: `remote`
3. `url`: `http://127.0.0.1:18800/mcp`
4. OAuth 选择 `No`
5. header 包含 `Authorization: Bearer pm-demo-token-20260517`

检查：
```bash
opencode mcp list
```

预期：`package-manager-remote connected`（或 `enabled` 且可调用工具）。

### 6.1 工具分层（含危险操作）
1. 读：`pm_health` `pm_list_packages` `pm_status` `pm_get_config`（`pm:read`）
2. 写：`pm_install` `pm_skill_install_guarded`（`pm:write`）
3. 管理：`pm_update_config_plan` `pm_confirm_plan` `pm_update_config_apply` `pm_uninstall_plan` `pm_uninstall_apply` `pm_rollback_config`（`pm:admin`）

---

## 7. 完整手工测试流程（逐步验收）

### 步骤 7.1：健康检查
自然语言输入：
`检查远端包管理服务健康状态`

预期：
1. 调用 `pm_health`。
2. 返回 `healthy=true`。

验证点：
1. `binary_exists=true`
2. `config_exists=true`
3. `state_parent_exists=true`

### 步骤 7.2：列包
输入：
`列出当前可安装产品`

预期：
1. 调用 `pm_list_packages`。
2. 返回至少一个产品，且含 `DevKit-Porting-Advisor`（如该产品启用）。

### 步骤 7.3：dry-run
输入：
`安装 DevKit-Porting-Advisor，先 dry-run`

预期：
1. 命中 skill 或走受控流程。
2. 调用链至少包含 `pm_health`、`pm_list_packages`、dry-run 安装步骤。
3. dry-run 返回 `status=success`。

### 步骤 7.4：真实安装
输入：
`执行真实安装 DevKit-Porting-Advisor 并返回状态`

预期：
1. 真实安装返回 `status=success`，或同版本已安装被 skip。
2. 返回最终状态。

### 步骤 7.5：状态复核
输入：
`调用 pm_status 查看 DevKit-Porting-Advisor 当前状态`

预期：
1. `installed_version` 存在。
2. `last_result=success`。

---

## 8. 远端一致性验证

### 步骤 8.1：容器内状态文件
```bash
docker exec openeuler-arm-mcp /bin/sh -lc 'cat /opt/package-manager/current/.package-manager/.install_state.yaml'
```

预期：
1. 目标产品记录与 opencode 返回一致。

### 步骤 8.2：工具直观检查（可选）
```bash
docker exec openeuler-arm-mcp /bin/sh -lc '/opt/package-manager/current/package-manager --help'
```

预期：帮助信息正常输出。

---

## 9. 负向测试（建议）

### 9.1 错误产品名
输入：
`安装 Not-Exist-Product，先 dry-run`

预期：
1. 返回 `unknown or disabled product`。
2. 给出可安装列表。

### 9.2 错误 token
操作：
1. 在 `opencode` 把 MCP header 改为错误 token。
2. 再执行 `检查远端包管理服务健康状态`。

预期：
1. 返回 `401 Unauthorized`。

### 9.3 危险操作未确认直接执行
直接调用 `pm_update_config_apply` 或 `pm_uninstall_apply`，不带/带错 `challenge_token`。

预期：
1. 返回 `confirm_required` / `confirm_expired` / `confirm_replayed`。
2. 不发生真实配置变更或卸载。

### 9.4 危险操作标准链路（plan -> confirm -> apply -> verify -> audit）
示例：配置修改
1. `pm_update_config_plan`
2. `pm_confirm_plan`
3. `pm_update_config_apply`（带 `challenge_token` + `idempotency_key`）
4. `pm_get_config` 回读验证
5. 检查审计：`/opt/package-manager/current/.package-manager/audit.log`

示例：卸载
1. `pm_uninstall_plan`
2. `pm_confirm_plan`
3. `pm_uninstall_apply`（带 `challenge_token` + `idempotency_key`）
4. `pm_status` 回读验证
5. 检查审计：`/opt/package-manager/current/.package-manager/audit.log`

---

## 10. 常见问题与处理

1. `401 Unauthorized`
- 校验 header token 与服务端 `--token` 一致。

2. `insufficient_scope`
- token scope 至少包含：
  - 读：`pm:read`
  - 写：`pm:write`

3. `lock_timeout`
- 检查锁文件路径是否可写：`PACKAGE_MANAGER_INSTALL_LOCK_FILE`。

4. `command_timeout`
- 调大 `PACKAGE_MANAGER_COMMAND_TIMEOUT_SECONDS`。

5. `mcp` 安装失败
- 确认使用 `/opt/cpython-3.11/bin/pip3.11` 而不是系统 Python 3.9 的 pip。

6. `SSE error: socket connection closed unexpectedly`
- 先看进程和日志：`ps -ef` + `tail /tmp/mcp-server.log`。
- 常见根因：
  - 进程未启动或启动后崩溃。
  - token 配置不一致。
  - 未带 `--public-base-url`（在较新 `mcp` SDK 下建议显式设置）。

7. `Session not found`
- 多发生在服务重启后客户端沿用旧 session-id。
- 启动参数增加 `--stateless-http`（本指南默认已包含）以降低会话耦合。
- 若仍出现，重开一次 opencode 会话或重新触发 MCP 初始化后再试。

8. 容器重启后服务失效
- 重新执行第 5 步（同步 + 杀旧 + 启新）。

9. `opencode mcp list` 本地异常（与远端无关）
- 若报本地数据库/权限错误，先单独验证远端可达性：
```bash
curl -sv -H 'Authorization: Bearer pm-demo-token-20260517' http://127.0.0.1:18800/mcp -m 5
```
- 预期返回 `406 Not Acceptable` 且提示需要 `text/event-stream`，说明端口和鉴权链路是通的。

---

## 11. 自动化测试补充

在项目本地执行：
```bash
pytest -q
pytest tests/test_control_plane.py -q
pytest tests/test_mcp_server_auth.py -q
pytest tests/test_mcp_server_e2e.py -q
```

预期：全部通过（受限环境可能对 e2e 出现 `skip`）。

---

## 12. 验收记录模板

- 执行日期：
- 测试人：
- 容器：`openeuler-arm-mcp`
- Python 版本：
- 7.1 health：通过/失败，证据：
- 7.2 list：通过/失败，证据：
- 7.3 dry-run：通过/失败，证据：
- 7.4 real install：通过/失败，证据：
- 7.5 status：通过/失败，证据：
- 8.1 容器状态一致性：通过/失败，证据：
- 9.x 负向测试：通过/失败，证据：
- 结论：通过 / 不通过
