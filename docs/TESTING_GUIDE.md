# package-manager 测试文档（UT + E2E + MCP）

## 1. 目标与范围
1. 安装主链路行为稳定（成功、跳过、失败、回滚、状态更新）。
2. MCP 控制面行为稳定（工具可用、鉴权授权、结构化返回）。
3. `opencode -> MCP -> package-manager` 端到端可手工验收。

## 2. 自动化测试分层
### 2.1 安装器与基础能力
- 覆盖配置、解析、下载、验签、安装器模板、状态锁。
- 命令：
```bash
pytest -q
```

### 2.2 MCP 控制面与鉴权
- `tests/test_control_plane.py`：
  - `pm_health/pm_list_packages/pm_status/pm_install`
  - dry-run 模式
  - 安装锁超时
  - 命令超时
- `tests/test_mcp_server_auth.py`：
  - 静态 token
  - HMAC token（过期/签名）
  - 组合 verifier
  - `auth-disabled` 非 loopback 拦截
- `tests/test_mcp_server_e2e.py`：
  - MCP streamable-http 协议级工具调用

命令：
```bash
pytest tests/test_control_plane.py -q
pytest tests/test_mcp_server_auth.py -q
pytest tests/test_mcp_server_e2e.py -q
```

## 3. 手工验收（opencode 全链路）

### 3.1 前置
1. `opencode mcp list` 中 `package-manager-remote` 为 `connected`。
2. 远端 MCP Server 已启动并可访问。
3. 若远端 `package-manager` 不支持 `--dry-run`，设置 `PACKAGE_MANAGER_MCP_DRY_RUN_MODE=simulate`。

### 3.2 验收步骤
在 `opencode` 会话中依次执行自然语言：
1. `检查远端包管理服务健康状态`
2. `列出当前可安装产品`
3. `安装 DevKit-Porting-Advisor，先 dry-run`
4. `执行真实安装 DevKit-Porting-Advisor 并返回状态`

建议追加：
1. `调用 pm_status 查看 DevKit-Porting-Advisor 当前状态`

### 3.3 通过标准
1. 第 1 步返回 `healthy=true`。
2. 第 2 步返回目标产品存在且 `enabled=true`。
3. 第 3 步 dry-run 返回 `status=success`。
4. 第 4 步真实安装返回 `status=success` 或“同版本已安装跳过”。
5. `pm_status` 返回 `installed_version` 与 `last_result=success`。

## 4. 常见失败与定位
1. `401 Unauthorized`
   - 校验 `Authorization` header、token 与 scope。
2. `insufficient_scope`
   - 读接口至少 `pm:read`，写接口至少 `pm:write`。
3. `lock_timeout`
   - 检查 `PACKAGE_MANAGER_INSTALL_LOCK_FILE` 是否位于可写目录。
4. `command_timeout`
   - 增加 `PACKAGE_MANAGER_COMMAND_TIMEOUT_SECONDS`。
5. `command_exec_error`
   - 检查 `PACKAGE_MANAGER_BINARY_PATH` 是否存在且可执行。
6. `No enabled package found`
   - 检查 `packages.yaml` 中产品 `enabled: true`。

## 5. 回归建议
1. 改动 `installer/*`：至少跑 `pytest -q`。
2. 改动 `control_plane.py` 或 `mcp_server.py`：至少跑 MCP 三套测试。
3. 交付前必须跑一次 `opencode` 手工验收四步链路。
