# package-manager

YAML 配置、自动下载、P7S 验签、安装执行的包管理器，支持通过 MCP 暴露为远端可调用能力。

## 核心能力
- 安装器主链路：配置加载 -> 选包 -> 下载/离线命中 -> 验签 -> 安装 -> 状态落盘
- 双版本语义：`project_version`（目录/状态）与 `artifact_version`（文件名）
- 下载可靠性：磁盘预检、重试、`.tmp` 原子替换、Range 续传
- 验签安全：`openssl cms -verify` detached `.p7s`
- 安装器分层：`BaseInstaller -> TarGzInstaller/RpmInstaller -> 产品子类`
- MCP 自动路由安装：先 `pm_probe_network`，再自动选择在线或离线分支
- 远端网络受限场景：本地下载并上传离线制品后再走远端安装
- MCP 鉴权与授权：静态 token + HMAC 短期 token，`pm:read/pm:write/pm:admin` scope 控制
- 控制面并发保护：安装互斥锁、命令超时、危险操作二次确认与审计日志

## MCP 工具总览
- 读：`pm_health` `pm_list_packages` `pm_status` `pm_get_config` `pm_probe_network` `pm_offline_manifest` `pm_check_offline_artifacts`
- 写：`pm_install` `pm_skill_install_guarded` `pm_offline_stage_and_install`
- 管理：`pm_update_config_plan` `pm_confirm_plan` `pm_update_config_apply` `pm_uninstall_plan` `pm_uninstall_apply` `pm_rollback_config`

## Skill 总览
- `package-manager-online-offline-auto-install`：安装默认入口，先探测再路由
- `package-manager-install-guarded`：受控安装子流程与兜底
- `package-manager-dangerous-ops-guarded`：危险操作标准链路（plan/confirm/apply/verify/audit）

## 目录结构
- `src/package_manager/main.py`：CLI 入口（支持 `--dry-run`）
- `src/package_manager/service.py`：安装编排
- `src/package_manager/installer/`：安装器实现与注册
- `src/package_manager/control_plane.py`：MCP 控制面适配
- `src/package_manager/mcp_server.py`：MCP Server 与鉴权
- `scripts/start_mcp_server.sh`：MCP 启动脚本
- `scripts/pm_offline_stage_and_upload.py`：本地下载 + 上传远端离线制品
- `scripts/generate_mcp_token.py`：HMAC 短期 token 生成
- `.opencode/skills/`：自然语言技能

## CLI 用法
```bash
python -m package_manager.main --name DevKit-Porting-Advisor
python -m package_manager.main --name DevKit-Porting-Advisor --dry-run
python -m package_manager.main --name devkit-porting
```

## MCP 快速启动
```bash
export PACKAGE_MANAGER_MCP_HOST=127.0.0.1
export PACKAGE_MANAGER_MCP_PORT=18880
export PACKAGE_MANAGER_MCP_PATH=/mcp
export PACKAGE_MANAGER_MCP_AUTH_DISABLED=true
./scripts/start_mcp_server.sh
```

## 测试
```bash
pytest -q
pytest tests/test_mcp_server_auth.py -q
pytest tests/test_mcp_server_e2e.py -q
```

## 文档索引
- [架构详细设计](/Users/fxl/pycharm_projects/package/docs/ARCHITECTURE_DESIGN.md)
- [开发者指南](/Users/fxl/pycharm_projects/package/docs/DEVELOPER_GUIDE.md)
- [测试指南](/Users/fxl/pycharm_projects/package/docs/TESTING_GUIDE.md)
- [远端 MCP 操作指南](/Users/fxl/pycharm_projects/package/docs/REMOTE_MCP_OPERATION_GUIDE.md)
- [Local MCP Bridge 手工验收指南](/Users/fxl/pycharm_projects/package/docs/LOCAL_MCP_BRIDGE_MANUAL_TEST_GUIDE.md)
- [OpenCode 自然语言验收（25.3.0）](/Users/fxl/pycharm_projects/package/docs/OPENCODE_NL_ACCEPTANCE_25_3_0.md)
