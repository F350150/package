# package-manager 测试文档（UT + E2E + MCP）

## 1. 目标与范围
1. 安装主链路行为稳定（成功、跳过、失败、回滚、状态更新）。
2. MCP 控制面行为稳定（工具可用、鉴权授权、结构化返回）。
3. `opencode -> MCP -> package-manager` 端到端链路可手工验收。

## 2. 自动化测试

### 2.1 全量回归
```bash
pytest -q
```

### 2.2 MCP 专项
```bash
pytest tests/test_control_plane.py -q
pytest tests/test_mcp_server_auth.py -q
pytest tests/test_mcp_server_e2e.py -q
```

覆盖点：
1. 控制面工具行为（health/list/status/install/probe/offline-manifest/offline-artifact-check）。
2. dry-run 与安装互斥锁。
3. 命令超时与结构化错误。
4. 静态 token / HMAC token / scope 授权。
5. streamable-http 协议级调用。
6. 危险操作五阶段：plan -> confirm -> apply -> verify -> audit。
7. challenge token 过期/重放防护、幂等键复用行为、配置回滚。

## 3. 手工测试入口

### 3.1 远端容器直连 MCP（推荐）
完整步骤（含 CPython 3.11 编译安装、启动、验收、负向测试）：
- [REMOTE_MCP_OPERATION_GUIDE.md](/Users/fxl/pycharm_projects/package/docs/REMOTE_MCP_OPERATION_GUIDE.md)

### 3.2 Local MCP Bridge（兜底）
当远端 Python/mcp 受限时使用：
- [LOCAL_MCP_BRIDGE_MANUAL_TEST_GUIDE.md](/Users/fxl/pycharm_projects/package/docs/LOCAL_MCP_BRIDGE_MANUAL_TEST_GUIDE.md)

## 4. 手工验收统一口径

核心步骤：
1. `安装 DevKit-Porting-Advisor，并返回每个阶段结果`
2. 观察第一阶段必须出现网络探测（`pm_probe_network`）。
3. 若探测 online：应走 `pm_skill_install_guarded -> pm_status`。
4. 若探测 offline：应走 `pm_offline_manifest -> 本地离线上传 -> pm_check_offline_artifacts -> pm_skill_install_guarded -> pm_status`。
5. 危险操作链路（建议工具级执行）：
   1. `pm_update_config_plan`
   2. `pm_confirm_plan`
   3. `pm_update_config_apply`
   4. `pm_uninstall_plan`
   5. `pm_confirm_plan`
   6. `pm_uninstall_apply`

通过标准：
1. 首步必须有网络探测并返回 `recommended_mode`。
2. 探测结果与实际执行分支一致（online/offline）。
3. offline 分支中离线制品检查必须 `ready_for_offline_install=true` 后再安装。
4. 最终 `status` 返回 `installed_version` 且 `last_result=success`（或同版本 skip 但结果成功）。
5. 危险操作未 confirm 时必须失败，confirm 后才能执行。
6. 审计日志存在对应记录。

## 5. 常见失败与定位

1. `401 Unauthorized`
- 校验 `Authorization` header 与 token。

2. `insufficient_scope`
- 读接口要 `pm:read`，写接口要 `pm:write`，危险操作要 `pm:admin`。

3. `lock_timeout`
- 检查 `PACKAGE_MANAGER_INSTALL_LOCK_FILE` 可写性。

4. `command_timeout`
- 提升 `PACKAGE_MANAGER_COMMAND_TIMEOUT_SECONDS`。

5. `command_exec_error`
- 检查 `PACKAGE_MANAGER_BINARY_PATH` 是否存在且可执行。

6. `No enabled package found`
- 检查 `packages.yaml` 产品 `enabled: true`。

7. `confirm_required` / `confirm_expired` / `confirm_replayed`
- 危险操作必须先 `pm_confirm_plan`。
- `challenge_token` 默认短期有效，且单次消费。

8. 走了 `pm_skill_install_guarded` 但没先探测网络
- 这是技能路由问题，应优先触发 `package-manager-online-offline-auto-install`。
- 检查 `.opencode/skills` 下两个安装 skill 的说明是否为最新版本。

## 6. 回归建议

1. 改动 `installer/*`：至少跑 `pytest -q`。
2. 改动 `control_plane.py` / `mcp_server.py`：至少跑 MCP 专项三套。
3. 发布前至少完成一次手工验收（第 4 节五步）。
