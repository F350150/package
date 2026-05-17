---
name: package-manager-dangerous-ops-guarded
description: 包管理危险操作防护技能。用于卸载和修改配置的自然语言请求，必须走 plan -> confirm -> apply -> verify -> audit 流程，不允许直接执行 apply。
---

## Scope

Use this skill when user intent includes:

- 卸载/移除/回滚某个产品
- 修改 packages.yaml / 改启用状态 / 改下载源 / 改版本策略
- 读取某个产品当前配置（例如“读取 DevKit-Porting-Advisor 当前配置”）
- 任何需要 `pm:admin` 的操作

## Required Tools

- `pm_get_config`
- `pm_update_config_plan`
- `pm_uninstall_plan`
- `pm_confirm_plan`
- `pm_update_config_apply`
- `pm_uninstall_apply`
- `pm_rollback_config`
- `pm_status`

## Mandatory Guardrail Flow

Read-only config request:
1. Call `pm_get_config` (use `product` or `path`).
2. Return only MCP result fields.
3. Do not execute local shell reads.

1. First run `*_plan` tool (`pm_update_config_plan` or `pm_uninstall_plan`).
2. Show summary: target, risk, expected changes.
3. Ask for explicit confirmation.
4. After confirmation, call `pm_confirm_plan`.
5. Call `*_apply` with:
   - `plan_id`
   - `challenge_token`
   - `idempotency_key` (new UUID)
   - `request_id` (traceable string)
6. Verify:
   - config: use `pm_get_config` read-back
   - uninstall: use `pm_status` read-back
7. Report concise final result.

## Hard Rules

- Never use local shell/file reads for config/state in this skill.
- Never call `pm_update_config_apply` or `pm_uninstall_apply` before `pm_confirm_plan`.
- Never reuse an old `challenge_token` (single-use).
- If apply returns `confirm_*` errors, stop and regenerate plan/confirm.
- For rollback request, call `pm_rollback_config` with a new `idempotency_key`.
