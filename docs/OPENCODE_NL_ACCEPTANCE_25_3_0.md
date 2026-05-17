# OpenCode 自然语言验收测试表（25.3.0 场景）

测试日期：2026-05-17  
环境：`openeuler-arm-mcp`（remote MCP）  
目标产品：`DevKit-Porting-Advisor`

## 1. 测试目标
1. 通过危险操作标准链路修改配置，支持 `25.3.0`。
2. 使用自然语言安装链路完成 `25.3.0` 安装。
3. 若失败，修复代码/技能并复测直至通过。

## 2. 测试表（含实测结果）

| Case ID | 自然语言输入/操作意图 | 预期工具链 | 预期结果 | 实测结果 | 证据摘要 |
|---|---|---|---|---|---|
| TC-2530-001 | “读取 DevKit-Porting-Advisor 当前配置” | `pm_get_config` | 返回当前 `project_version/artifact_version/supported_versions` | 通过 | 变更前为 `26.0.RC1` |
| TC-2530-002 | “把 DevKit-Porting-Advisor 调整为支持 25.3.0（先计划）” | `pm_update_config_plan` | 返回 `plan_id`、`risk_level`、`changes` | 通过 | `risk_level=high`，包含 3 项变更 |
| TC-2530-003 | “确认执行刚才配置变更” | `pm_confirm_plan` + `pm_update_config_apply` | apply 成功，配置落地 | 通过 | `status=success`，返回 `config_backup_version` |
| TC-2530-004 | “再次读取 DevKit-Porting-Advisor 配置” | `pm_get_config` | 看到 `project_version=25.3.0`，`artifact_version=25.3.0` | 通过 | 实测配置已更新 |
| TC-2530-005 (初测) | “安装 DevKit-Porting-Advisor” | `pm_skill_install_guarded` | 真实安装成功 | 失败 | 下载与验签成功，但旧安装器不识别新包布局，报 `No Porting-Advisor payload directory found` |
| TC-2530-006 (修复后复测) | “安装 DevKit-Porting-Advisor” | `pm_skill_install_guarded` | 真实安装成功，状态更新到 `25.3.0` | 通过 | `install.status=success`，`pm_status.installed_version=25.3.0` |

## 3. 问题与修复

### 3.1 初测失败原因
`25.3.0` 包结构与 `26.0.RC1` 不同：  
旧逻辑仅支持 `Sql-Analysis-*.tar.gz + jre-linux-*.tar.gz`。  
新包为现代布局（含 `porting.zip`、`jre-linux-*.tar.gz`、`cmd/bin/sql-analysis-*.jar`），导致 payload 目录探测失败。

### 3.2 已完成修复
1. 安装器兼容新旧两种 Porting-Advisor 布局：
   - 文件：`src/package_manager/installer/utils.py`
2. 新增现代布局单测：
   - 文件：`tests/test_porting_advisor_layout_modern.py`
3. 危险操作配置更新策略支持 `project_version` 字段：
   - 文件：`src/package_manager/control_plane.py`
4. 新增源码执行 wrapper（用于快速联调/热修复验收）：
   - 文件：`scripts/package-manager-source-wrapper.sh`

## 4. 复测结论
1. 配置修改链路：`plan -> confirm -> apply -> verify` 通过。
2. `25.3.0` 安装链路通过，最终状态：
   - `installed_version=25.3.0`
   - `last_result=success`
3. 本场景验收结论：**通过**。
