---
name: package-manager-online-offline-auto-install
description: 包安装默认入口技能（最高优先级）。任何安装意图都必须先探测远端网络，再自动选择在线或离线安装分支。
---

## Scope

Use this skill as the default install path for package-manager.

Trigger on any install intent, for example:
- 安装 / 部署 / 升级某个产品
- 校验后安装
- 自然语言下发安装流程

Do not require user to mention network status.

Priority rule:
- If this skill is available, any install intent MUST trigger this skill first.
- `package-manager-install-guarded` is a sub-flow only, called by this skill after routing.

## Required MCP Tools

- `pm_probe_network`
- `pm_offline_manifest`
- `pm_check_offline_artifacts`
- `pm_skill_install_guarded`
- `pm_status`

## Required Inputs for Offline Upload

- Prefer SSH path: `ssh_target=user@host` (optional `ssh_port` and `ssh_key`)
- Demo/container fallback: `docker_container=openeuler-arm-mcp`
- If server env has defaults (`PACKAGE_MANAGER_OFFLINE_*`), these args can be omitted.

## Flow

1. For `package-manager-remote` (remote MCP server) do client-side orchestration:
   - call `pm_probe_network(product)`
   - if `recommended_mode=online`: call `pm_skill_install_guarded(product)` then `pm_status(product)`
   - if `recommended_mode=offline`:
     - call `pm_offline_manifest(product)`
     - run local script:
       `python3 scripts/pm_offline_stage_and_upload.py --manifest-file <file> --docker-container openeuler-arm-mcp`
       or SSH mode:
       `python3 scripts/pm_offline_stage_and_upload.py --manifest-file <file> --ssh-target <user@host> [--ssh-port ...] [--ssh-key ...]`
     - call `pm_check_offline_artifacts(product)` and require `ready_for_offline_install=true`
     - call `pm_skill_install_guarded(product)`
     - call `pm_status(product)`
2. For local MCP bridge mode, `pm_offline_stage_and_install` can be used as one-shot helper.

## Hard Rules

- In remote MCP mode, do not call `pm_offline_stage_and_install` for offline branch because download must happen on local PC.
- Always return which branch executed (`online` or `offline`) and final install status.
