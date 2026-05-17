---
name: package-manager-install-guarded
description: Guarded package-manager workflow over MCP. Use when user asks to install or verify package products such as DevKit-Porting-Advisor or devkit-porting, and you should run health check, list, dry-run, real install, and status confirmation in order.
---

## Scope

Use this skill when the user wants package installation or installation validation through MCP tools.

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

## Example User Requests

- "Install DevKit-Porting-Advisor with safety checks."
- "Run dry-run first, then real install if safe."
- "Verify package manager health and then install devkit-porting."
