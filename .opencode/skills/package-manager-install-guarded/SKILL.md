---
name: package-manager-install-guarded
description: 使用 MCP 做包安装时的默认技能（中文/英文请求都应触发）。当用户表达“安装/部署/升级/验证安装/先 dry-run/再真实安装/返回安装状态”等意图时，必须优先使用本技能，而不是直接只调 pm_install。标准顺序是 health -> list -> dry-run -> real install -> status。适用于 DevKit-Porting-Advisor、devkit-porting 等产品。
---

## Scope

Use this skill when the user wants package installation or installation validation through MCP tools.

Hard boundary:
- Do not read local files for package-manager config/state in this skill.
- Do not use shell file discovery (`ls/find/glob/cat`) for runtime config checks.
- Only use MCP tools from `package-manager-remote`.

### Trigger Phrases (must trigger this skill)

- “安装 DevKit-Porting-Advisor，先 dry-run”
- “执行真实安装并返回状态”
- “检查安装是否成功”
- “安装/升级/部署 devkit-porting”
- "install xxx with dry-run first"
- "run guarded install and return final status"

When these intents appear, do not stop after a single `pm_install` call.

Use product names as configured in runtime YAML, for example:

- `DevKit-Porting-Advisor`
- `devkit-porting`

## Required Tools

- `pm_health`
- `pm_list_packages`
- `pm_status`
- `pm_install`
- `pm_skill_install_guarded`

## Standard Flow

1. Call `pm_health`.
2. If unhealthy, stop and return the health failure details.
3. Call `pm_list_packages` to confirm target product exists and is enabled.
4. Prefer calling `pm_skill_install_guarded` for one-shot guarded execution.
5. If `pm_skill_install_guarded` is unavailable, run fallback:
   - `pm_install` with `dry_run=true`
   - `pm_install` with `dry_run=false`
   - `pm_status` for final confirmation
6. Return concise phase-by-phase result with exit or status fields.

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
