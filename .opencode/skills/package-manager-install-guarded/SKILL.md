---
name: package-manager-install-guarded
description: 包安装兜底技能。若被直接触发，必须先做网络探测并自动路由在线/离线；禁止跳过探测直接安装。
---

## Scope

This skill is a fallback when routing skill is not selected.

If triggered directly, it must still perform network probe and route automatically.

Hard boundary:
- Do not read local files for package-manager config/state in this skill.
- Do not use shell file discovery (`ls/find/glob/cat`) for runtime config checks.
- Only use MCP tools from `package-manager-remote`.

### Trigger Phrases (fallback)

- “安装 DevKit-Porting-Advisor，先 dry-run”
- “执行真实安装并返回状态”
- “检查安装是否成功”
- “安装/升级/部署 devkit-porting”
- "install xxx with dry-run first"
- "run guarded install and return final status"

When these intents appear directly from user, run probe-first routing in this skill itself.

Use product names as configured in runtime YAML, for example:

- `DevKit-Porting-Advisor`
- `devkit-porting`

## Required Tools

- `pm_probe_network`
- `pm_offline_manifest`
- `pm_check_offline_artifacts`
- `pm_health`
- `pm_list_packages`
- `pm_status`
- `pm_install`
- `pm_skill_install_guarded`

## Standard Flow

1. Call `pm_probe_network(product)` first. This step is mandatory.
2. If `recommended_mode=online`:
   - call `pm_health`
   - call `pm_list_packages`
   - call `pm_skill_install_guarded(product)` (or low-level fallback)
   - call `pm_status(product)`
3. If `recommended_mode=offline`:
   - call `pm_offline_manifest(product)`
   - explicitly stop and ask for local stage/upload execution by wrapper/local skill (do not fake success)
   - after upload, call `pm_check_offline_artifacts(product)` and require `ready_for_offline_install=true`
   - call `pm_skill_install_guarded(product)`
   - call `pm_status(product)`
4. Return concise phase-by-phase result with executed branch (`online`/`offline`).

## Output Contract

Return a short structured summary:

- target product
- health result
- dry-run result
- real install result
- final status result
- request ids when available

## Error Handling

- If product is missing or disabled, stop and show available products from `pm_list_packages`.
- If dry-run fails, do not execute real install.
- If real install fails, report error output tail and suggest re-run after fix.
- If user asks to read or change config/version target, hand over to dangerous-ops/config workflow (`pm_get_config`, `pm_update_config_plan`, `pm_confirm_plan`, `pm_update_config_apply`) before install.

## Example User Requests

- "Install DevKit-Porting-Advisor with safety checks."
- "Run dry-run first, then real install if safe."
- "Verify package manager health and then install devkit-porting."
