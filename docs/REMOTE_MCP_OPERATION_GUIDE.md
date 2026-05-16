# package-manager 远端 MCP Server 操作指南

本文档对应本仓库的远端 MCP 方案，目标是让本地 `opencode` 通过自然语言驱动远端包管理流程。

## 1. 两条落地路线

### 1.1 Local MCP Bridge（本地桥接，推荐起步）
- 本地起 `package_manager.mcp_server`，`binary-path` 指向远端执行代理（如 docker wrapper/ssh wrapper）。
- 优点：部署快、不暴露远端 MCP 端口。
- 缺点：本机必须在线。

### 1.2 Remote MCP Server（远端直连，生产目标）
- 在远端主机/容器直接起 `package_manager.mcp_server`。
- 优点：集中化、可共享、易统一审计。
- 缺点：需要处理鉴权、证书、网络暴露、运维。

> 本文默认讲 `Remote MCP Server`，并补充桥接模式兜底。

## 2. 部署视图

参考图：
- [mcp_remote_deployment_view.puml](/Users/fxl/pycharm_projects/package/docs/puml/mcp_remote_deployment_view.puml)
- [mcp_guarded_install_sequence.puml](/Users/fxl/pycharm_projects/package/docs/puml/mcp_guarded_install_sequence.puml)

核心链路：
1. `opencode` 选择模型（建议 `alibaba-cn/glm-5`）。
2. `opencode` 调用 MCP 工具（`pm_*`）。
3. `package_manager.mcp_server` 做鉴权 + scope 授权。
4. `control_plane` 执行健康检查/列包/安装。
5. 控制面调用 `package-manager` 二进制，并更新 install_state。

## 3. 前置要求

远端需具备：
1. 已部署 package-manager 产物：
   - `/opt/package-manager/current/package-manager`
   - `/opt/package-manager/current/config/packages.yaml`
   - `/opt/package-manager/current/.package-manager/.install_state.yaml`
2. Python 运行时建议 `3.10+`（推荐 `3.11+`）。
3. 可安装 `mcp` 依赖（`python -m pip install mcp`）。

> 注意：某些 `openEuler 22.03` 默认 `Python 3.9` 环境无法直接安装 `mcp`，此时建议先走 Local MCP Bridge。

## 4. 启动远端 MCP Server

### 4.1 最小安全配置（静态 token）
```bash
export PACKAGE_MANAGER_MCP_HOST=0.0.0.0
export PACKAGE_MANAGER_MCP_PORT=18800
export PACKAGE_MANAGER_MCP_PATH=/mcp

export PACKAGE_MANAGER_MCP_TOKEN='replace-with-long-random-token'
export PACKAGE_MANAGER_MCP_TOKEN_SCOPES='pm:read,pm:write'

export PACKAGE_MANAGER_BINARY_PATH=/opt/package-manager/current/package-manager
export PACKAGE_MANAGER_CONFIG_FILE=/opt/package-manager/current/config/packages.yaml
export PACKAGE_MANAGER_INSTALL_STATE_FILE=/opt/package-manager/current/.package-manager/.install_state.yaml
export PACKAGE_MANAGER_INSTALL_LOCK_FILE=/opt/package-manager/current/.package-manager/.mcp_install.lock

./scripts/start_mcp_server.sh
```

### 4.2 升级版配置（HMAC 短期 token）
```bash
export PACKAGE_MANAGER_MCP_HMAC_SECRET='replace-with-hmac-secret'
./scripts/start_mcp_server.sh
```

本地生成 token：
```bash
python scripts/generate_mcp_token.py \
  --secret 'replace-with-hmac-secret' \
  --client-id 'opencode-client' \
  --scopes 'pm:read,pm:write' \
  --ttl-seconds 3600
```

### 4.3 调试配置（仅 loopback）
```bash
export PACKAGE_MANAGER_MCP_HOST=127.0.0.1
export PACKAGE_MANAGER_MCP_AUTH_DISABLED=true
./scripts/start_mcp_server.sh
```

## 5. 在 opencode 注册 MCP

```bash
opencode mcp add
```

填写示例：
- `name`: `package-manager-remote`
- `type`: `remote`
- `url`: `http://<远端IP或域名>:18800/mcp`
- `headers`（静态 token）：`{"Authorization":"Bearer replace-with-long-random-token"}`
- `oauth`: `false`
- `enabled`: `true`

检查连通：
```bash
opencode mcp list
```

## 6. Skill 与工具关系

- Skill 文件：`.opencode/skills/package-manager-install-guarded/SKILL.md`
- Skill 只是编排规范，不替代远端工具。
- 真正执行仍由 MCP 工具完成：
  - `pm_health`
  - `pm_list_packages`
  - `pm_status`
  - `pm_install`
  - `pm_skill_install_guarded`

## 7. 手工全链路验收（必须）

在 `opencode` 会话执行：
1. `检查远端包管理服务健康状态`
2. `列出当前可安装产品`
3. `安装 DevKit-Porting-Advisor，先 dry-run`
4. `执行真实安装 DevKit-Porting-Advisor 并返回状态`
5. `调用 pm_status 查看 DevKit-Porting-Advisor 当前状态`

通过判据：
1. health 返回 `healthy=true`。
2. list 包含目标产品且已启用。
3. dry-run 返回 `status=success`。
4. 真实安装返回 `status=success` 或“同版本已安装跳过”。
5. status 返回 `installed_version` 和 `last_result=success`。

## 8. Local MCP Bridge 兜底方案

当远端 `Python/mcp` 受限时：
1. 本地启动 MCP Server。
2. `binary-path` 指向本地 wrapper（wrapper 内转发到远端执行）。
3. `config-file/state-file` 使用远端同步或镜像文件。

示例启动：
```bash
PYTHONPATH=src \
PACKAGE_MANAGER_MCP_DRY_RUN_MODE=simulate \
python -m package_manager.mcp_server \
  --host 127.0.0.1 \
  --port 18880 \
  --path /mcp \
  --binary-path /private/tmp/pm-mcp-bridge/pm-container-wrapper.sh \
  --config-file /private/tmp/pm-mcp-bridge/packages.yaml \
  --state-file /private/tmp/pm-mcp-bridge/install_state.yaml \
  --auth-disabled
```

## 9. 常见问题

1. `401 Unauthorized`
- 检查 token 是否一致，header 是否正确。

2. `insufficient_scope`
- 读工具需要 `pm:read`，写工具需要 `pm:write`。

3. `auth-disabled on non-loopback host is blocked`
- 非 loopback 默认禁止裸奔；仅临时调试可显式 `--allow-auth-disabled-nonlocal`。

4. `lock_timeout`
- 检查 `PACKAGE_MANAGER_INSTALL_LOCK_FILE` 是否可写，是否有长期持锁。

5. `command_timeout`
- 增大 `PACKAGE_MANAGER_COMMAND_TIMEOUT_SECONDS`。

6. 远端无法安装 `mcp`
- 升级 Python 到 `3.10+`，或先采用 Local MCP Bridge。
