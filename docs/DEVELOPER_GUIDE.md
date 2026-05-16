# 开发者文档

## 1. 先读什么
1. `src/package_manager/main.py`：CLI 参数与退出码映射。
2. `src/package_manager/service.py`：安装业务编排、`--dry-run` 分流。
3. `src/package_manager/installer/base.py`：模板方法、回滚、清理、dry-run 预检。
4. `src/package_manager/installer/registry.py`：安装器自动发现与映射。
5. `src/package_manager/control_plane.py`：MCP 工具对应的控制面封装。
6. `src/package_manager/mcp_server.py`：MCP Server、鉴权与 scope 授权。
7. `src/package_manager/file_lock.py` + `control_plane._install_lock`：状态锁 + MCP 安装互斥锁。
8. `src/package_manager/resolver.py` / `downloader.py` / `verifier.py`：安装底层能力。

## 2. 两条运行主线
1. CLI 线：`main -> service -> installer`。
2. MCP 线：`mcp_server(FastMCP) -> control_plane -> package-manager binary`。

## 3. 版本语义（必须遵守）
1. `project_version`：用于项目目录与 install_state 版本比较。
2. `artifact_version`：用于文件名拼装。
3. `rpm_arch_separator`：rpm 版本与架构分隔符（`-` 或 `.`）。

## 4. MCP 设计约束
1. MCP 工具必须只做白名单动作，不接受任意 shell。
2. 授权最小化：
   - `pm_health/pm_list_packages/pm_status` 需要 `pm:read`
   - `pm_install/pm_skill_install_guarded` 需要 `pm:write`
3. 鉴权默认开启，`auth-disabled` 仅允许 loopback；非 loopback 需显式 override。
4. 所有工具返回结构化结果，必须包含 `status/request_id/timestamp`（适用时）。

## 5. 如何新增一个产品
1. 在 `packages.yaml` 增加产品配置：`product/project_version/artifact_version/package_format/install_dir`。
2. 在 `src/package_manager/installer/` 新增产品安装器，并暴露 `REGISTER`。
3. 补齐 UT + E2E（至少覆盖 pre-check/install/fail/rollback）。
4. 若产品会被 MCP 调用，补 `control_plane` 的产品验证分支测试。

## 6. 如何新增一个 MCP 工具
1. 在 `mcp_server.py` 注册 `@mcp.tool(...)`。
2. 为工具分配必需 scope（`require_scope(...)`）。
3. 在 `control_plane.py` 增加对应能力，禁止透传任意参数到 shell。
4. 增加 UT/E2E：
   - `tests/test_control_plane.py`
   - `tests/test_mcp_server_auth.py`
   - `tests/test_mcp_server_e2e.py`

## 7. Dry-run 策略
1. `command` 模式：真实执行 `package-manager --dry-run`。
2. `simulate` 模式：不执行命令，仅返回模拟成功。
3. 通过 `PACKAGE_MANAGER_MCP_DRY_RUN_MODE` 控制。

## 8. 并发与超时策略
1. MCP 安装互斥锁：`PACKAGE_MANAGER_INSTALL_LOCK_FILE`。
2. 锁等待超时：`PACKAGE_MANAGER_INSTALL_LOCK_TIMEOUT_SECONDS`。
3. 命令超时：`PACKAGE_MANAGER_COMMAND_TIMEOUT_SECONDS`。
4. 结构化错误码：`lock_timeout/command_timeout/command_exec_error/command_failed`。

## 9. 代码风格与边界
1. 优先组合已有模块，不在入口层堆分支。
2. 不在文档外硬编码路径；路径由配置和环境变量驱动。
3. 新增外部契约（CLI 参数、MCP 返回字段）必须同步更新测试与文档。
