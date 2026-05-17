# package-manager 远端 MCP Server 操作指南（容器直连版）

本文档给出“远端容器直连 MCP”的落地、联调和手工验收流程。

适用日期：2026-05-18

---

## 1. 方案定位

### 1.1 主路径：Remote MCP Server（容器直连）
- 在远端容器内运行 `package_manager.mcp_server`。
- 本地 `opencode` 直接连接远端 MCP 地址。
- 自然语言安装默认先探测网络，再自动选择在线或离线分支。

### 1.2 兜底路径：Local MCP Bridge
- 当远端 Python/mcp 运行受限时使用。
- 详见 [LOCAL_MCP_BRIDGE_MANUAL_TEST_GUIDE.md](/Users/fxl/pycharm_projects/package/docs/LOCAL_MCP_BRIDGE_MANUAL_TEST_GUIDE.md)。

---

## 2. 目标链路

`opencode -> skill(auto-router) -> remote MCP server -> control_plane -> package-manager binary -> install_state`

通过标准：
1. 安装请求先调用 `pm_probe_network`。
2. `recommended_mode=online` 时走在线安装。
3. `recommended_mode=offline` 时先完成离线制品投放，再执行安装。
4. 最终 `pm_status` 返回目标产品 `last_result=success`。

---

## 3. 前置条件

### 3.1 容器与端口
```bash
docker ps -a | grep openeuler-arm-mcp
```

要求：
1. `openeuler-arm-mcp` 容器存在且 `Up`。
2. 端口有 `18800:18800` 映射。

### 3.2 远端产物检查
```bash
docker exec openeuler-arm-mcp /bin/sh -lc '
ls -la /opt/package-manager/current/package-manager &&
ls -la /opt/package-manager/current/config/packages.yaml &&
ls -la /opt/package-manager/current/.package-manager/.install_state.yaml
'
```

---

## 4. 启动远端 MCP 服务

### 4.1 同步关键代码（每次改动后）
```bash
docker cp /Users/fxl/pycharm_projects/package/src/package_manager/control_plane.py \
  openeuler-arm-mcp:/opt/package-manager/source/src/package_manager/control_plane.py

docker cp /Users/fxl/pycharm_projects/package/src/package_manager/mcp_server.py \
  openeuler-arm-mcp:/opt/package-manager/source/src/package_manager/mcp_server.py

docker cp /Users/fxl/pycharm_projects/package/scripts/pm_offline_stage_and_upload.py \
  openeuler-arm-mcp:/opt/package-manager/source/scripts/pm_offline_stage_and_upload.py

docker exec openeuler-arm-mcp /bin/sh -lc 'chmod +x /opt/package-manager/source/scripts/pm_offline_stage_and_upload.py'
```

### 4.2 启动命令（token 鉴权）
```bash
docker exec openeuler-arm-mcp /bin/sh -lc "pkill -f 'package_manager.mcp_server' || true"

docker exec openeuler-arm-mcp /bin/sh -lc \
"nohup /opt/cpython-3.11/bin/python3.11 -m package_manager.mcp_server \
  --host 0.0.0.0 \
  --port 18800 \
  --path /mcp \
  --binary-path /opt/package-manager/source/scripts/package-manager-source-wrapper.sh \
  --config-file /opt/package-manager/current/config/packages.yaml \
  --state-file /opt/package-manager/current/.package-manager/.install_state.yaml \
  --token 'pm-demo-token-20260517' \
  --token-scopes 'pm:read,pm:write,pm:admin' \
  --public-base-url 'http://127.0.0.1:18800' \
  --stateless-http \
  >/tmp/pm_mcp.log 2>&1 &"
```

### 4.3 检查
```bash
docker exec openeuler-arm-mcp /bin/sh -lc "ps -ef | grep -E 'package_manager.mcp_server' | grep -v grep"
curl -i http://127.0.0.1:18800/mcp
```

预期：
1. 进程存在。
2. 未带 token 访问 `/mcp` 返回 `401 Unauthorized`（正常）。

---

## 5. 在 opencode 注册远端 MCP

`opencode.json` 示例：

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

检查：
```bash
opencode mcp list
```

---

## 6. 工具分层

1. 读：`pm_health` `pm_list_packages` `pm_status` `pm_get_config` `pm_probe_network` `pm_offline_manifest` `pm_check_offline_artifacts`
2. 写：`pm_install` `pm_skill_install_guarded` `pm_offline_stage_and_install`（local bridge/同机执行更适用）
3. 管理：`pm_update_config_plan` `pm_confirm_plan` `pm_update_config_apply` `pm_uninstall_plan` `pm_uninstall_apply` `pm_rollback_config`

---

## 7. 自动路由安装验收（推荐主用例）

输入：
`安装 DevKit-Porting-Advisor，并返回每个阶段结果`

预期调用顺序：
1. `pm_probe_network`
2. online 分支：`pm_skill_install_guarded -> pm_status`
3. offline 分支：`pm_offline_manifest -> 本地离线投放 -> pm_check_offline_artifacts -> pm_skill_install_guarded -> pm_status`

关键验证点：
1. 第一阶段必须出现网络探测。
2. 分支与 `recommended_mode` 一致。
3. 最终 `last_result=success`。

---

## 8. 远端网络受限场景测试（offline 分支）

### 8.1 人工制造远端网络受限
```bash
docker exec openeuler-arm-mcp /bin/sh -lc "grep -n 'kunpeng-repo.obs.cn-north-4.myhuaweicloud.com' /etc/hosts || true"
docker exec openeuler-arm-mcp /bin/sh -lc "echo '127.0.0.1 kunpeng-repo.obs.cn-north-4.myhuaweicloud.com' >> /etc/hosts"
```

### 8.2 清空远端离线制品（确保触发上传）
```bash
docker exec openeuler-arm-mcp /bin/sh -lc "rm -f /opt/package-manager/source/_internal/packages/DevKit-Porting-Advisor/* || true"
```

### 8.3 在 opencode 执行自然语言安装
输入：
`安装 DevKit-Porting-Advisor，并返回每个阶段结果`

预期：
1. `pm_probe_network` 返回 `recommended_mode=offline`。
2. 发生本地下载+上传步骤。
3. 离线文件检查为 `ready_for_offline_install=true`。
4. 安装与状态结果成功。

---

## 9. 常见问题

1. `401 Unauthorized`
- 检查 `Authorization` header 与 `--token` 是否一致。

2. `insufficient_scope`
- 检查 token scope 是否覆盖对应工具。

3. `Session not found`
- 服务重启后旧会话失效，重开会话或重新触发 MCP 初始化。

4. 只走 `pm_skill_install_guarded` 没走探测
- 技能路由问题，检查 `.opencode/skills` 是否是最新版本。

5. offline 分支中下载失败
- 远端模式下应由本地执行下载上传，不应在远端容器内直接下载。
