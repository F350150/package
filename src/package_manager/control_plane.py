"""Package manager control-plane adapter for MCP tools."""

from __future__ import annotations

import copy
import errno
import fcntl
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import yaml

from package_manager.config import RuntimeConfig, load_raw_config_from_path, load_runtime_config_from_path, runtime_config_from_raw
from package_manager.install_state import load_install_state


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def tail_lines(text: str, limit: int = 80) -> str:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if len(lines) <= limit:
        return "\n".join(lines)
    return "\n".join(lines[-limit:])


def dry_run_not_supported(output_tail: str) -> bool:
    lowered = (output_tail or "").lower()
    signatures = (
        "unrecognized arguments: --dry-run",
        "unknown option: --dry-run",
        "no such option: --dry-run",
    )
    return any(item in lowered for item in signatures)


@dataclass(frozen=True)
class ControlPlaneSettings:
    """Runtime paths and command execution settings."""

    binary_path: Path
    config_file: Path
    state_file: Path
    command_timeout_seconds: int = 7200
    lock_file: Path = Path("/opt/package-manager/current/.package-manager/.mcp_install.lock")
    install_lock_timeout_seconds: int = 60
    dry_run_mode: str = "command"
    config_lock_file: Path = Path("/opt/package-manager/current/.package-manager/.mcp_config.lock")
    uninstall_lock_file: Path = Path("/opt/package-manager/current/.package-manager/.mcp_uninstall.lock")
    confirm_lock_file: Path = Path("/opt/package-manager/current/.package-manager/.mcp_confirm.lock")
    confirm_used_file: Path = Path("/opt/package-manager/current/.package-manager/.mcp_confirm_used.json")
    idempotency_file: Path = Path("/opt/package-manager/current/.package-manager/.mcp_idempotency.json")
    audit_file: Path = Path("/opt/package-manager/current/.package-manager/audit.log")
    config_backup_dir: Path = Path("/opt/package-manager/current/.package-manager/config-backups")
    plan_ttl_seconds: int = 300
    confirm_ttl_seconds: int = 60

    @classmethod
    def from_env(cls) -> "ControlPlaneSettings":
        binary_path = Path(
            os.getenv("PACKAGE_MANAGER_BINARY_PATH", "/opt/package-manager/current/package-manager")
        ).expanduser()
        config_file = Path(
            os.getenv("PACKAGE_MANAGER_CONFIG_FILE", "/opt/package-manager/current/config/packages.yaml")
        ).expanduser()
        state_file = Path(
            os.getenv(
                "PACKAGE_MANAGER_INSTALL_STATE_FILE",
                "/opt/package-manager/current/.package-manager/.install_state.yaml",
            )
        ).expanduser()
        timeout = int(os.getenv("PACKAGE_MANAGER_COMMAND_TIMEOUT_SECONDS", "7200"))
        lock_file = Path(
            os.getenv(
                "PACKAGE_MANAGER_INSTALL_LOCK_FILE",
                "/opt/package-manager/current/.package-manager/.mcp_install.lock",
            )
        ).expanduser()
        lock_timeout = int(os.getenv("PACKAGE_MANAGER_INSTALL_LOCK_TIMEOUT_SECONDS", "60"))
        dry_run_mode = (os.getenv("PACKAGE_MANAGER_MCP_DRY_RUN_MODE", "command") or "command").strip().lower()
        if dry_run_mode not in {"command", "simulate"}:
            dry_run_mode = "command"
        config_lock_file = Path(
            os.getenv(
                "PACKAGE_MANAGER_CONFIG_LOCK_FILE",
                "/opt/package-manager/current/.package-manager/.mcp_config.lock",
            )
        ).expanduser()
        uninstall_lock_file = Path(
            os.getenv(
                "PACKAGE_MANAGER_UNINSTALL_LOCK_FILE",
                "/opt/package-manager/current/.package-manager/.mcp_uninstall.lock",
            )
        ).expanduser()
        confirm_lock_file = Path(
            os.getenv(
                "PACKAGE_MANAGER_CONFIRM_LOCK_FILE",
                "/opt/package-manager/current/.package-manager/.mcp_confirm.lock",
            )
        ).expanduser()
        confirm_used_file = Path(
            os.getenv(
                "PACKAGE_MANAGER_CONFIRM_USED_FILE",
                "/opt/package-manager/current/.package-manager/.mcp_confirm_used.json",
            )
        ).expanduser()
        idempotency_file = Path(
            os.getenv(
                "PACKAGE_MANAGER_IDEMPOTENCY_FILE",
                "/opt/package-manager/current/.package-manager/.mcp_idempotency.json",
            )
        ).expanduser()
        audit_file = Path(
            os.getenv(
                "PACKAGE_MANAGER_AUDIT_FILE",
                "/opt/package-manager/current/.package-manager/audit.log",
            )
        ).expanduser()
        config_backup_dir = Path(
            os.getenv(
                "PACKAGE_MANAGER_CONFIG_BACKUP_DIR",
                "/opt/package-manager/current/.package-manager/config-backups",
            )
        ).expanduser()
        plan_ttl = int(os.getenv("PACKAGE_MANAGER_PLAN_TTL_SECONDS", "300"))
        confirm_ttl = int(os.getenv("PACKAGE_MANAGER_CONFIRM_TTL_SECONDS", "60"))
        return cls(
            binary_path=binary_path,
            config_file=config_file,
            state_file=state_file,
            command_timeout_seconds=timeout,
            lock_file=lock_file,
            install_lock_timeout_seconds=lock_timeout,
            dry_run_mode=dry_run_mode,
            config_lock_file=config_lock_file,
            uninstall_lock_file=uninstall_lock_file,
            confirm_lock_file=confirm_lock_file,
            confirm_used_file=confirm_used_file,
            idempotency_file=idempotency_file,
            audit_file=audit_file,
            config_backup_dir=config_backup_dir,
            plan_ttl_seconds=max(30, plan_ttl),
            confirm_ttl_seconds=max(15, confirm_ttl),
        )


class PackageManagerControlPlane:
    """Whitelist actions used by MCP tools."""

    def __init__(self, settings: ControlPlaneSettings):
        self.settings = settings
        secret = (
            os.getenv("PACKAGE_MANAGER_MCP_CONFIRM_SECRET", "").strip()
            or os.getenv("PACKAGE_MANAGER_MCP_TOKEN", "").strip()
            or f"pm-confirm-{uuid.uuid4().hex}"
        )
        self._confirm_secret = secret.encode("utf-8")
        self._plans: Dict[str, Dict[str, Any]] = {}

    def _runtime(self) -> RuntimeConfig:
        return load_runtime_config_from_path(self.settings.config_file)

    def _enabled_products(self) -> List[Dict[str, Any]]:
        runtime = self._runtime()
        result: List[Dict[str, Any]] = []
        for pkg in runtime.packages:
            if not pkg.enabled:
                continue
            result.append(
                {
                    "product": pkg.product,
                    "project_version": pkg.version,
                    "artifact_version": pkg.artifact_version,
                    "package_format": pkg.package_format,
                    "install_dir": pkg.install_dir,
                    "supported_versions": list(pkg.supported_versions or []),
                }
            )
        return result

    def _validate_product(self, product: str) -> Dict[str, Any]:
        target = (product or "").strip()
        if not target:
            raise ValueError("product must not be empty")
        for item in self._enabled_products():
            if item["product"].lower() == target.lower():
                return item
        raise ValueError(f"unknown or disabled product: {product}")

    def list_packages(self) -> Dict[str, Any]:
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        packages = self._enabled_products()
        return {
            "request_id": request_id,
            "status": "success",
            "count": len(packages),
            "packages": packages,
            "timestamp": now_utc(),
        }

    def status(self, product: Optional[str] = None) -> Dict[str, Any]:
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        state = load_install_state(self.settings.state_file)
        products = state.get("products", {})
        if not isinstance(products, dict):
            products = {}
        if product:
            matched_key = None
            for key in products:
                if key.lower() == product.lower():
                    matched_key = key
                    break
            return {
                "request_id": request_id,
                "status": "success",
                "product": product,
                "state": products.get(matched_key),
                "timestamp": now_utc(),
            }
        return {
            "request_id": request_id,
            "status": "success",
            "products": products,
            "timestamp": now_utc(),
        }

    def health(self) -> Dict[str, Any]:
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        checks = {
            "binary_exists": self.settings.binary_path.exists(),
            "binary_executable": os.access(self.settings.binary_path, os.X_OK),
            "config_exists": self.settings.config_file.exists(),
            "state_parent_exists": self.settings.state_file.parent.exists(),
        }
        ok = all(checks.values())
        help_output = ""
        exit_code = None
        if ok:
            try:
                proc = subprocess.run(
                    [str(self.settings.binary_path), "--help"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                exit_code = proc.returncode
                help_output = tail_lines((proc.stdout or "") + "\n" + (proc.stderr or ""), limit=40)
                ok = proc.returncode == 0
            except subprocess.TimeoutExpired as exc:
                ok = False
                help_output = tail_lines((exc.stdout or "") + "\n" + (exc.stderr or ""), limit=40)
            except OSError as exc:
                ok = False
                help_output = str(exc)
        return {
            "request_id": request_id,
            "status": "success" if ok else "error",
            "healthy": ok,
            "checks": checks,
            "binary_help_exit_code": exit_code,
            "binary_help_output_tail": help_output,
            "timestamp": now_utc(),
        }

    def install(self, product: str, dry_run: bool = False) -> Dict[str, Any]:
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        selected = self._validate_product(product)
        command = [str(self.settings.binary_path), "--name", selected["product"]]
        if dry_run and self.settings.dry_run_mode == "command":
            command.append("--dry-run")
        started_at = now_utc()
        if dry_run:
            if self.settings.dry_run_mode == "simulate":
                return {
                    "request_id": request_id,
                    "status": "success",
                    "action": "install",
                    "dry_run": True,
                    "dry_run_mode": "simulate",
                    "product": selected["product"],
                    "command": command,
                    "started_at": started_at,
                    "ended_at": now_utc(),
                    "exit_code": 0,
                    "message": "simulate dry-run only, command not executed",
                }
            run_result = self._run_command(command, timeout=self.settings.command_timeout_seconds)
            return {
                "request_id": request_id,
                "status": run_result["status"],
                "action": "install",
                "dry_run": True,
                "dry_run_mode": "command",
                "product": selected["product"],
                "command": command,
                "started_at": started_at,
                "ended_at": now_utc(),
                "exit_code": run_result.get("exit_code"),
                "message": "dry-run completed" if run_result["status"] == "success" else run_result["message"],
                "error_code": run_result.get("error_code"),
                "output_tail": run_result.get("output_tail", ""),
            }
        try:
            with self._install_lock(request_id=request_id, product=selected["product"]):
                run_result = self._run_command(
                    command,
                    timeout=self.settings.command_timeout_seconds,
                    extra_env={"PACKAGE_MANAGER_INSTALL_STATE_FILE": str(self.settings.state_file)},
                )
        except TimeoutError as exc:
            return {
                "request_id": request_id,
                "status": "error",
                "action": "install",
                "dry_run": False,
                "product": selected["product"],
                "command": command,
                "started_at": started_at,
                "ended_at": now_utc(),
                "exit_code": None,
                "message": str(exc),
                "error_code": "lock_timeout",
                "output_tail": "",
            }
        return {
            "request_id": request_id,
            "status": run_result["status"],
            "action": "install",
            "dry_run": False,
            "product": selected["product"],
            "command": command,
            "started_at": started_at,
            "ended_at": now_utc(),
            "exit_code": run_result.get("exit_code"),
            "message": "install completed" if run_result["status"] == "success" else run_result["message"],
            "error_code": run_result.get("error_code"),
            "output_tail": run_result.get("output_tail", ""),
        }

    def install_with_guardrails(self, product: str) -> Dict[str, Any]:
        """Skill-like guarded install flow."""

        request_id = f"req-{uuid.uuid4().hex[:12]}"
        started_at = now_utc()
        health = self.health()
        if not health.get("healthy", False):
            return {
                "request_id": request_id,
                "status": "error",
                "action": "install_with_guardrails",
                "product": product,
                "phase": "health",
                "message": "health check failed",
                "health": health,
                "started_at": started_at,
                "ended_at": now_utc(),
            }

        packages = self.list_packages()
        try:
            self._validate_product(product)
        except ValueError as exc:
            return {
                "request_id": request_id,
                "status": "error",
                "action": "install_with_guardrails",
                "product": product,
                "phase": "validate_product",
                "message": str(exc),
                "packages": packages,
                "started_at": started_at,
                "ended_at": now_utc(),
            }

        dry_run_result = self.install(product=product, dry_run=True)
        if (
            dry_run_result.get("status") != "success"
            and self.settings.dry_run_mode == "command"
            and dry_run_not_supported(str(dry_run_result.get("output_tail", "")))
        ):
            dry_run_result = {
                "request_id": dry_run_result.get("request_id"),
                "status": "success",
                "action": "install",
                "dry_run": True,
                "dry_run_mode": "simulate_fallback",
                "product": product,
                "command": dry_run_result.get("command", []),
                "started_at": dry_run_result.get("started_at"),
                "ended_at": now_utc(),
                "exit_code": 0,
                "message": "dry-run flag unsupported by binary, fallback to simulate dry-run",
                "fallback_from": dry_run_result,
            }
        if dry_run_result.get("status") != "success":
            return {
                "request_id": request_id,
                "status": "error",
                "action": "install_with_guardrails",
                "product": product,
                "phase": "dry_run",
                "message": "dry-run failed",
                "dry_run_result": dry_run_result,
                "started_at": started_at,
                "ended_at": now_utc(),
            }

        install_result = self.install(product=product, dry_run=False)
        status_result = self.status(product=product)
        final_status = "success" if install_result.get("status") == "success" else "error"
        return {
            "request_id": request_id,
            "status": final_status,
            "action": "install_with_guardrails",
            "product": product,
            "phases": {
                "health": health,
                "list_packages": packages,
                "dry_run": dry_run_result,
                "install": install_result,
                "status": status_result,
            },
            "started_at": started_at,
            "ended_at": now_utc(),
        }

    def get_config(self, path: Optional[str] = None, product: Optional[str] = None) -> Dict[str, Any]:
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        raw = self._load_raw_config()
        selected: Any = raw
        if product:
            found = self._find_package_node(raw, product)
            selected = found
        elif path:
            selected = self._read_config_path(raw, path)
        return {
            "request_id": request_id,
            "status": "success",
            "path": path,
            "product": product,
            "value": selected,
            "config_sha256": self._sha256_json(raw),
            "timestamp": now_utc(),
        }

    def update_config_plan(
        self,
        operations: Sequence[Dict[str, Any]],
        actor: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        raw = self._load_raw_config()
        current_hash = self._sha256_json(raw)
        try:
            new_raw, changes, risk = self._apply_config_operations(raw, operations)
            runtime_config_from_raw(new_raw)
        except ValueError as exc:
            return {
                "request_id": request_id,
                "status": "error",
                "action": "update_config_plan",
                "message": str(exc),
                "error_code": "validation_failed",
                "timestamp": now_utc(),
            }
        new_hash = self._sha256_json(new_raw)
        plan_id = self._store_plan(
            action="config_update",
            actor=actor,
            payload={
                "operations": list(operations),
                "before_hash": current_hash,
                "after_hash": new_hash,
                "changes": changes,
                "risk_level": risk,
                "reason": (reason or "").strip(),
            },
            digest_source={"operations": list(operations), "before_hash": current_hash, "after_hash": new_hash},
        )
        return {
            "request_id": request_id,
            "status": "success",
            "action": "update_config_plan",
            "plan_id": plan_id,
            "risk_level": risk,
            "changes": changes,
            "before_hash": current_hash,
            "after_hash": new_hash,
            "confirm_hint": "call pm_confirm_plan with this plan_id before apply",
            "expires_at": self._plans[plan_id]["expires_at"],
            "timestamp": now_utc(),
        }

    def uninstall_plan(self, product: str, actor: str, reason: str = "") -> Dict[str, Any]:
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        try:
            package = self._find_package(product)
        except ValueError as exc:
            return {
                "request_id": request_id,
                "status": "error",
                "action": "uninstall_plan",
                "message": str(exc),
                "error_code": "validation_failed",
                "timestamp": now_utc(),
            }
        state = load_install_state(self.settings.state_file)
        products = state.get("products", {}) if isinstance(state.get("products", {}), dict) else {}
        installed = product in products or any(str(k).lower() == product.lower() for k in products)
        install_root = self.settings.binary_path.parent.resolve()
        target_path = (install_root / package["install_dir"]).resolve()
        if not str(target_path).startswith(str(install_root)):
            return {
                "request_id": request_id,
                "status": "error",
                "action": "uninstall_plan",
                "message": f"unsafe install_dir path for product: {product}",
                "error_code": "validation_failed",
                "timestamp": now_utc(),
            }
        path_exists = target_path.exists()
        sibling_hits = self._same_install_dir_products(package["install_dir"], product)
        risk = "high" if sibling_hits else ("medium" if path_exists or installed else "low")
        payload = {
            "product": package["product"],
            "install_dir": package["install_dir"],
            "target_path": str(target_path),
            "installed_in_state": installed,
            "target_path_exists": path_exists,
            "dependent_products": sibling_hits,
            "reason": (reason or "").strip(),
            "risk_level": risk,
        }
        plan_id = self._store_plan(
            action="uninstall",
            actor=actor,
            payload=payload,
            digest_source=payload,
        )
        return {
            "request_id": request_id,
            "status": "success",
            "action": "uninstall_plan",
            "plan_id": plan_id,
            "risk_level": risk,
            "plan": payload,
            "confirm_hint": "call pm_confirm_plan with this plan_id before apply",
            "expires_at": self._plans[plan_id]["expires_at"],
            "timestamp": now_utc(),
        }

    def confirm_plan(self, plan_id: str, actor: str) -> Dict[str, Any]:
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        plan = self._plans.get(plan_id)
        if not plan:
            return {
                "request_id": request_id,
                "status": "error",
                "action": "confirm_plan",
                "message": f"plan not found: {plan_id}",
                "error_code": "validation_failed",
                "timestamp": now_utc(),
            }
        now_ts = int(time.time())
        if now_ts >= int(plan.get("expires_ts", 0)):
            self._plans.pop(plan_id, None)
            return {
                "request_id": request_id,
                "status": "error",
                "action": "confirm_plan",
                "message": f"plan expired: {plan_id}",
                "error_code": "validation_failed",
                "timestamp": now_utc(),
            }
        plan_actor = str(plan.get("actor", "")).strip()
        if plan_actor and plan_actor != actor:
            return {
                "request_id": request_id,
                "status": "error",
                "action": "confirm_plan",
                "message": f"plan actor mismatch: owner={plan_actor}, caller={actor}",
                "error_code": "policy_denied",
                "timestamp": now_utc(),
            }
        token = self._issue_confirm_token(plan_id=plan_id, plan_digest=str(plan["digest"]), actor=actor)
        return {
            "request_id": request_id,
            "status": "success",
            "action": "confirm_plan",
            "plan_id": plan_id,
            "challenge_token": token,
            "expires_in_seconds": self.settings.confirm_ttl_seconds,
            "timestamp": now_utc(),
        }

    def update_config_apply(
        self,
        plan_id: str,
        challenge_token: str,
        request_id: str,
        idempotency_key: str,
        actor: str,
    ) -> Dict[str, Any]:
        existing = self._idempotency_get("config_update", idempotency_key)
        if existing is not None:
            return existing
        plan = self._validate_apply_plan(
            plan_id=plan_id,
            expected_action="config_update",
            challenge_token=challenge_token,
            actor=actor,
        )
        if plan.get("status") == "error":
            return plan

        started_at = now_utc()
        lock_timeout = max(5, self.settings.install_lock_timeout_seconds)
        try:
            with self._file_lock(self.settings.config_lock_file, lock_timeout, request_id, f"config_update:{plan_id}"):
                before_raw = self._load_raw_config()
                before_hash = self._sha256_json(before_raw)
                payload = plan["plan"]["payload"]
                expected_before = payload.get("before_hash")
                if before_hash != expected_before:
                    result = {
                        "request_id": request_id,
                        "status": "error",
                        "action": "update_config_apply",
                        "error_code": "verify_failed",
                        "message": "config changed since plan, please regenerate plan",
                        "before_hash": before_hash,
                        "expected_before_hash": expected_before,
                        "ended_at": now_utc(),
                    }
                    self._idempotency_put("config_update", idempotency_key, result)
                    return result

                new_raw, changes, _risk = self._apply_config_operations(before_raw, payload["operations"])
                runtime_config_from_raw(new_raw)
                version_id = self._backup_config(before_raw)
                self._write_yaml_atomic(self.settings.config_file, new_raw)
                after_raw = self._load_raw_config()
                after_hash = self._sha256_json(after_raw)
                if after_hash != payload.get("after_hash"):
                    result = {
                        "request_id": request_id,
                        "status": "error",
                        "action": "update_config_apply",
                        "error_code": "verify_failed",
                        "message": "post-apply hash mismatch",
                        "after_hash": after_hash,
                        "expected_after_hash": payload.get("after_hash"),
                        "config_backup_version": version_id,
                        "ended_at": now_utc(),
                    }
                    self._audit(
                        actor=actor,
                        tool="pm_update_config_apply",
                        request_id=request_id,
                        result="error",
                        before_hash=before_hash,
                        after_hash=after_hash,
                        details=result,
                    )
                    self._idempotency_put("config_update", idempotency_key, result)
                    return result

                result = {
                    "request_id": request_id,
                    "status": "success",
                    "action": "update_config_apply",
                    "plan_id": plan_id,
                    "changes": changes,
                    "config_backup_version": version_id,
                    "before_hash": before_hash,
                    "after_hash": after_hash,
                    "started_at": started_at,
                    "ended_at": now_utc(),
                }
                self._audit(
                    actor=actor,
                    tool="pm_update_config_apply",
                    request_id=request_id,
                    result="success",
                    before_hash=before_hash,
                    after_hash=after_hash,
                    details={"plan_id": plan_id, "changes_count": len(changes)},
                )
                self._idempotency_put("config_update", idempotency_key, result)
                return result
        except TimeoutError as exc:
            result = {
                "request_id": request_id,
                "status": "error",
                "action": "update_config_apply",
                "error_code": "lock_timeout",
                "message": str(exc),
                "ended_at": now_utc(),
            }
            self._idempotency_put("config_update", idempotency_key, result)
            return result

    def uninstall_apply(
        self,
        plan_id: str,
        challenge_token: str,
        request_id: str,
        idempotency_key: str,
        actor: str,
    ) -> Dict[str, Any]:
        existing = self._idempotency_get("uninstall", idempotency_key)
        if existing is not None:
            return existing
        plan = self._validate_apply_plan(
            plan_id=plan_id,
            expected_action="uninstall",
            challenge_token=challenge_token,
            actor=actor,
        )
        if plan.get("status") == "error":
            return plan
        payload = plan["plan"]["payload"]
        product = str(payload["product"])
        target_path = Path(str(payload["target_path"]))
        state_before = load_install_state(self.settings.state_file)
        before_hash = self._sha256_json(state_before)
        started_at = now_utc()
        lock_timeout = max(5, self.settings.install_lock_timeout_seconds)
        try:
            with self._file_lock(self.settings.uninstall_lock_file, lock_timeout, request_id, f"uninstall:{product}"):
                removed_path = False
                if target_path.exists():
                    removed_path = self._safe_remove_path(target_path)
                state = load_install_state(self.settings.state_file)
                products = state.get("products", {})
                removed_state = False
                if isinstance(products, dict):
                    target_key = None
                    for key in list(products.keys()):
                        if str(key).lower() == product.lower():
                            target_key = key
                            break
                    if target_key is not None:
                        products.pop(target_key, None)
                        removed_state = True
                self._write_yaml_atomic(self.settings.state_file, state)
                verify_state = self.status(product=product)
                verify_ok = verify_state.get("state") is None and not target_path.exists()
                after_hash = self._sha256_json(state)
                if not verify_ok:
                    result = {
                        "request_id": request_id,
                        "status": "error",
                        "action": "uninstall_apply",
                        "error_code": "verify_failed",
                        "message": "post-uninstall verification failed",
                        "verify": verify_state,
                        "removed_path": removed_path,
                        "removed_state": removed_state,
                        "ended_at": now_utc(),
                    }
                    self._audit(
                        actor=actor,
                        tool="pm_uninstall_apply",
                        request_id=request_id,
                        result="error",
                        before_hash=before_hash,
                        after_hash=after_hash,
                        details=result,
                    )
                    self._idempotency_put("uninstall", idempotency_key, result)
                    return result
                result = {
                    "request_id": request_id,
                    "status": "success",
                    "action": "uninstall_apply",
                    "product": product,
                    "plan_id": plan_id,
                    "removed_path": removed_path,
                    "removed_state": removed_state,
                    "verify": verify_state,
                    "started_at": started_at,
                    "ended_at": now_utc(),
                }
                self._audit(
                    actor=actor,
                    tool="pm_uninstall_apply",
                    request_id=request_id,
                    result="success",
                    before_hash=before_hash,
                    after_hash=after_hash,
                    details={"product": product, "removed_path": removed_path, "removed_state": removed_state},
                )
                self._idempotency_put("uninstall", idempotency_key, result)
                return result
        except TimeoutError as exc:
            result = {
                "request_id": request_id,
                "status": "error",
                "action": "uninstall_apply",
                "error_code": "lock_timeout",
                "message": str(exc),
                "ended_at": now_utc(),
            }
            self._idempotency_put("uninstall", idempotency_key, result)
            return result

    def rollback_config(self, version_id: str, request_id: str, idempotency_key: str, actor: str) -> Dict[str, Any]:
        existing = self._idempotency_get("rollback_config", idempotency_key)
        if existing is not None:
            return existing
        backup_path = self.settings.config_backup_dir / version_id
        if not backup_path.exists():
            result = {
                "request_id": request_id,
                "status": "error",
                "action": "rollback_config",
                "error_code": "validation_failed",
                "message": f"backup version not found: {version_id}",
                "ended_at": now_utc(),
            }
            self._idempotency_put("rollback_config", idempotency_key, result)
            return result
        try:
            with self._file_lock(
                self.settings.config_lock_file,
                max(5, self.settings.install_lock_timeout_seconds),
                request_id,
                f"rollback:{version_id}",
            ):
                current_raw = self._load_raw_config()
                before_hash = self._sha256_json(current_raw)
                rollback_raw = load_raw_config_from_path(backup_path)
                runtime_config_from_raw(rollback_raw)
                rollback_to = self._sha256_json(rollback_raw)
                self._backup_config(current_raw)
                self._write_yaml_atomic(self.settings.config_file, rollback_raw)
                after_raw = self._load_raw_config()
                after_hash = self._sha256_json(after_raw)
                if after_hash != rollback_to:
                    result = {
                        "request_id": request_id,
                        "status": "error",
                        "action": "rollback_config",
                        "error_code": "verify_failed",
                        "message": "post-rollback verification failed",
                        "expected_after_hash": rollback_to,
                        "actual_after_hash": after_hash,
                        "ended_at": now_utc(),
                    }
                    self._idempotency_put("rollback_config", idempotency_key, result)
                    return result
                result = {
                    "request_id": request_id,
                    "status": "success",
                    "action": "rollback_config",
                    "version_id": version_id,
                    "before_hash": before_hash,
                    "after_hash": after_hash,
                    "ended_at": now_utc(),
                }
                self._audit(
                    actor=actor,
                    tool="pm_rollback_config",
                    request_id=request_id,
                    result="success",
                    before_hash=before_hash,
                    after_hash=after_hash,
                    details={"version_id": version_id},
                )
                self._idempotency_put("rollback_config", idempotency_key, result)
                return result
        except TimeoutError as exc:
            result = {
                "request_id": request_id,
                "status": "error",
                "action": "rollback_config",
                "error_code": "lock_timeout",
                "message": str(exc),
                "ended_at": now_utc(),
            }
            self._idempotency_put("rollback_config", idempotency_key, result)
            return result

    def _run_command(self, command: List[str], timeout: int, extra_env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            success = proc.returncode == 0
            return {
                "status": "success" if success else "error",
                "exit_code": proc.returncode,
                "message": "command completed" if success else "command failed",
                "error_code": None if success else "command_failed",
                "output_tail": tail_lines(combined, limit=120),
            }
        except subprocess.TimeoutExpired as exc:
            timed_output = ((exc.stdout or "") + "\n" + (exc.stderr or "")).strip()
            return {
                "status": "error",
                "exit_code": None,
                "message": f"command timeout after {timeout}s",
                "error_code": "command_timeout",
                "output_tail": tail_lines(timed_output, limit=120),
            }
        except OSError as exc:
            return {
                "status": "error",
                "exit_code": None,
                "message": f"command execute failed: {exc}",
                "error_code": "command_exec_error",
                "output_tail": "",
            }

    def _load_raw_config(self) -> Dict[str, Any]:
        return load_raw_config_from_path(self.settings.config_file)

    def _find_package_node(self, raw: Dict[str, Any], product: str) -> Dict[str, Any]:
        packages = raw.get("packages", [])
        if not isinstance(packages, list):
            raise ValueError("packages section is invalid")
        for item in packages:
            if not isinstance(item, dict):
                continue
            if str(item.get("product", "")).strip().lower() == product.strip().lower():
                return item
        raise ValueError(f"product not found in config: {product}")

    def _find_package(self, product: str) -> Dict[str, Any]:
        runtime = self._runtime()
        target = (product or "").strip().lower()
        for pkg in runtime.packages:
            if pkg.product.strip().lower() == target:
                return {
                    "product": pkg.product,
                    "project_version": pkg.version,
                    "artifact_version": pkg.artifact_version,
                    "package_format": pkg.package_format,
                    "install_dir": pkg.install_dir,
                    "enabled": pkg.enabled,
                }
        raise ValueError(f"unknown product: {product}")

    def _same_install_dir_products(self, install_dir: str, excluded_product: str) -> List[str]:
        runtime = self._runtime()
        result: List[str] = []
        normalized = (install_dir or "").strip()
        for pkg in runtime.packages:
            if pkg.product.strip().lower() == excluded_product.strip().lower():
                continue
            if str(pkg.install_dir).strip() == normalized:
                result.append(pkg.product)
        return sorted(result)

    def _read_config_path(self, raw: Dict[str, Any], path: str) -> Any:
        text = (path or "").strip()
        if not text:
            return raw
        if text.startswith("packages["):
            match = re.match(r"^packages\[(.+?)\]\.(\w+)$", text)
            if not match:
                raise ValueError(f"unsupported config path: {path}")
            product = match.group(1)
            field = match.group(2)
            node = self._find_package_node(raw, product)
            if field not in node:
                raise ValueError(f"field not found on package {product}: {field}")
            return node[field]
        cursor: Any = raw
        for token in text.split("."):
            if not isinstance(cursor, dict) or token not in cursor:
                raise ValueError(f"path not found: {path}")
            cursor = cursor[token]
        return cursor

    def _apply_config_operations(
        self,
        raw: Dict[str, Any],
        operations: Sequence[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str]:
        if not operations:
            raise ValueError("operations must not be empty")
        updated = copy.deepcopy(raw)
        changes: List[Dict[str, Any]] = []
        risk_order = {"low": 1, "medium": 2, "high": 3}
        risk = "low"
        for idx, op in enumerate(operations):
            if not isinstance(op, dict):
                raise ValueError(f"operation[{idx}] must be object")
            op_type = str(op.get("op", "set")).strip().lower()
            path = str(op.get("path", "")).strip()
            value = op.get("value")
            if op_type != "set":
                raise ValueError(f"operation[{idx}] unsupported op: {op_type}")
            if not path:
                raise ValueError(f"operation[{idx}] missing path")
            before, level = self._set_config_value(updated, path, value)
            risk = level if risk_order[level] > risk_order[risk] else risk
            changes.append({"path": path, "before": before, "after": value})
        return updated, changes, risk

    def _set_config_value(self, raw: Dict[str, Any], path: str, value: Any) -> Tuple[Any, str]:
        allowed_top_paths = {
            "download_defaults.base_url": "medium",
            "download_defaults.signature_suffix": "medium",
            "download_defaults.timeout_seconds": "low",
            "download_defaults.retry": "low",
            "download_defaults.cache_policy": "medium",
            "verify_defaults.signature_type": "high",
            "verify_defaults.signature_format": "high",
            "verify_defaults.verify_chain": "high",
        }
        if path in allowed_top_paths:
            head, tail = path.split(".", 1)
            node = raw.get(head)
            if not isinstance(node, dict):
                raise ValueError(f"invalid config section: {head}")
            before = node.get(tail)
            node[tail] = value
            return before, allowed_top_paths[path]

        pkg_match = re.match(r"^packages\[(.+?)\]\.(enabled|supported_versions|artifact_version|project_version)$", path)
        if pkg_match:
            product = pkg_match.group(1)
            field = pkg_match.group(2)
            node = self._find_package_node(raw, product)
            before = node.get(field)
            if field == "enabled" and not isinstance(value, bool):
                raise ValueError("packages[...].enabled must be bool")
            if field == "supported_versions":
                if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
                    raise ValueError("packages[...].supported_versions must be non-empty string list")
            if field == "artifact_version":
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("packages[...].artifact_version must be non-empty string")
            if field == "project_version":
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("packages[...].project_version must be non-empty string")
            node[field] = value
            risk = "high" if field in {"enabled", "project_version"} and (value is False or field == "project_version") else "medium"
            return before, risk
        raise ValueError(f"path not allowed by policy: {path}")

    def _store_plan(self, action: str, actor: str, payload: Dict[str, Any], digest_source: Dict[str, Any]) -> str:
        now_ts = int(time.time())
        plan_id = f"plan-{uuid.uuid4().hex[:16]}"
        digest = self._sha256_json(digest_source)
        expires_ts = now_ts + self.settings.plan_ttl_seconds
        self._plans[plan_id] = {
            "plan_id": plan_id,
            "action": action,
            "actor": actor,
            "digest": digest,
            "payload": payload,
            "created_at": now_utc(),
            "expires_at": datetime.fromtimestamp(expires_ts, tz=timezone.utc).isoformat(),
            "expires_ts": expires_ts,
        }
        self._cleanup_expired_plans(now_ts)
        return plan_id

    def _cleanup_expired_plans(self, now_ts: Optional[int] = None) -> None:
        current = int(time.time()) if now_ts is None else now_ts
        expired = [plan_id for plan_id, plan in self._plans.items() if int(plan.get("expires_ts", 0)) <= current]
        for plan_id in expired:
            self._plans.pop(plan_id, None)

    def _issue_confirm_token(self, plan_id: str, plan_digest: str, actor: str) -> str:
        now_ts = int(time.time())
        payload = {
            "plan_id": plan_id,
            "plan_digest": plan_digest,
            "actor": actor,
            "iat": now_ts,
            "exp": now_ts + self.settings.confirm_ttl_seconds,
            "jti": uuid.uuid4().hex,
        }
        payload_b64 = self._b64url_encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signing = f"pmc1.{payload_b64}".encode("utf-8")
        signature = hmac.new(self._confirm_secret, signing, hashlib.sha256).digest()
        return f"pmc1.{payload_b64}.{self._b64url_encode(signature)}"

    def _validate_apply_plan(
        self,
        plan_id: str,
        expected_action: str,
        challenge_token: str,
        actor: str,
    ) -> Dict[str, Any]:
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        self._cleanup_expired_plans()
        plan = self._plans.get(plan_id)
        if not plan:
            return {
                "request_id": request_id,
                "status": "error",
                "error_code": "validation_failed",
                "message": f"plan not found: {plan_id}",
            }
        if plan.get("action") != expected_action:
            return {
                "request_id": request_id,
                "status": "error",
                "error_code": "validation_failed",
                "message": f"plan action mismatch: expected={expected_action}, actual={plan.get('action')}",
            }
        verify = self._verify_confirm_token(challenge_token, plan_id=plan_id, plan_digest=str(plan["digest"]), actor=actor)
        if verify["status"] != "success":
            return verify
        replay = self._consume_confirm_jti(str(verify["jti"]), int(verify["exp"]))
        if replay is not None:
            return replay
        return {"status": "success", "plan": plan}

    def _verify_confirm_token(self, token: str, plan_id: str, plan_digest: str, actor: str) -> Dict[str, Any]:
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        raw = (token or "").strip()
        if not raw.startswith("pmc1."):
            return {
                "request_id": request_id,
                "status": "error",
                "error_code": "confirm_required",
                "message": "missing or invalid challenge token",
            }
        parts = raw.split(".")
        if len(parts) != 3:
            return {
                "request_id": request_id,
                "status": "error",
                "error_code": "confirm_required",
                "message": "invalid challenge token format",
            }
        _, payload_b64, sig_b64 = parts
        signing = f"pmc1.{payload_b64}".encode("utf-8")
        expected = hmac.new(self._confirm_secret, signing, hashlib.sha256).digest()
        provided = self._b64url_decode(sig_b64)
        if provided is None or not hmac.compare_digest(provided, expected):
            return {
                "request_id": request_id,
                "status": "error",
                "error_code": "confirm_required",
                "message": "invalid challenge signature",
            }
        payload_bytes = self._b64url_decode(payload_b64)
        if payload_bytes is None:
            return {
                "request_id": request_id,
                "status": "error",
                "error_code": "confirm_required",
                "message": "invalid challenge payload",
            }
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception:
            return {
                "request_id": request_id,
                "status": "error",
                "error_code": "confirm_required",
                "message": "challenge payload decode failed",
            }
        exp = int(payload.get("exp", 0))
        if int(time.time()) >= exp:
            return {
                "request_id": request_id,
                "status": "error",
                "error_code": "confirm_expired",
                "message": "challenge token expired",
            }
        if str(payload.get("plan_id", "")) != plan_id:
            return {
                "request_id": request_id,
                "status": "error",
                "error_code": "confirm_required",
                "message": "challenge plan mismatch",
            }
        if str(payload.get("plan_digest", "")) != plan_digest:
            return {
                "request_id": request_id,
                "status": "error",
                "error_code": "confirm_required",
                "message": "challenge digest mismatch",
            }
        token_actor = str(payload.get("actor", ""))
        if token_actor != actor:
            return {
                "request_id": request_id,
                "status": "error",
                "error_code": "policy_denied",
                "message": f"challenge actor mismatch: token={token_actor}, caller={actor}",
            }
        jti = str(payload.get("jti", ""))
        if not jti:
            return {
                "request_id": request_id,
                "status": "error",
                "error_code": "confirm_required",
                "message": "challenge jti missing",
            }
        return {"status": "success", "jti": jti, "exp": exp}

    def _consume_confirm_jti(self, jti: str, exp: int) -> Optional[Dict[str, Any]]:
        self.settings.confirm_used_file.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock(
            self.settings.confirm_lock_file,
            max(5, self.settings.install_lock_timeout_seconds),
            "confirm-jti",
            jti,
        ):
            data = self._read_json(self.settings.confirm_used_file, default={})
            if not isinstance(data, dict):
                data = {}
            now_ts = int(time.time())
            data = {k: int(v) for k, v in data.items() if int(v) > now_ts}
            if jti in data:
                return {
                    "request_id": f"req-{uuid.uuid4().hex[:12]}",
                    "status": "error",
                    "error_code": "confirm_replayed",
                    "message": "challenge token replayed",
                }
            data[jti] = int(exp)
            self._write_json(self.settings.confirm_used_file, data)
            return None

    def _idempotency_get(self, action: str, key: str) -> Optional[Dict[str, Any]]:
        text = (key or "").strip()
        if not text:
            return None
        data = self._read_json(self.settings.idempotency_file, default={})
        if not isinstance(data, dict):
            return None
        hit = data.get(f"{action}:{text}")
        if isinstance(hit, dict):
            return hit
        return None

    def _idempotency_put(self, action: str, key: str, result: Dict[str, Any]) -> None:
        text = (key or "").strip()
        if not text:
            return
        self.settings.idempotency_file.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock(
            self.settings.idempotency_file.with_suffix(".lock"),
            max(5, self.settings.install_lock_timeout_seconds),
            "idempotency",
            f"{action}:{text}",
        ):
            data = self._read_json(self.settings.idempotency_file, default={})
            if not isinstance(data, dict):
                data = {}
            data[f"{action}:{text}"] = result
            self._write_json(self.settings.idempotency_file, data)

    def _audit(
        self,
        actor: str,
        tool: str,
        request_id: str,
        result: str,
        before_hash: str,
        after_hash: str,
        details: Dict[str, Any],
    ) -> None:
        self.settings.audit_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": now_utc(),
            "actor": actor,
            "tool": tool,
            "request_id": request_id,
            "result": result,
            "before_hash": before_hash,
            "after_hash": after_hash,
            "details": details,
        }
        with self.settings.audit_file.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")

    def _backup_config(self, raw: Dict[str, Any]) -> str:
        self.settings.config_backup_dir.mkdir(parents=True, exist_ok=True)
        version_id = f"config-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.yaml"
        path = self.settings.config_backup_dir / version_id
        self._write_yaml_atomic(path, raw)
        return version_id

    def _safe_remove_path(self, target_path: Path) -> bool:
        install_root = self.settings.binary_path.parent.resolve()
        resolved = target_path.resolve()
        if not str(resolved).startswith(str(install_root)):
            raise ValueError(f"unsafe delete target: {target_path}")
        if not resolved.exists():
            return False
        if resolved.is_dir():
            shutil.rmtree(resolved)
            return True
        resolved.unlink(missing_ok=True)
        return True

    @contextmanager
    def _file_lock(self, lock_path: Path, timeout_seconds: int, request_id: str, target: str) -> Iterator[None]:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + max(1, timeout_seconds)
        with lock_path.open("a+", encoding="utf-8") as handle:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if time.time() >= deadline:
                        raise TimeoutError(f"lock timeout target={target} request_id={request_id} lock={lock_path}")
                    time.sleep(0.2)
            try:
                handle.seek(0)
                handle.truncate(0)
                handle.write(
                    f"request_id={request_id}\ntarget={target}\npid={os.getpid()}\nacquired_at={now_utc()}\n"
                )
                handle.flush()
                yield
            finally:
                try:
                    handle.seek(0)
                    handle.truncate(0)
                    handle.flush()
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=True, sort_keys=True)
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def _write_yaml_atomic(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                yaml.safe_dump(payload, fp, sort_keys=False, allow_unicode=False)
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def _sha256_json(self, payload: Any) -> str:
        text = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _b64url_encode(self, raw: bytes) -> str:
        import base64

        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _b64url_decode(self, raw: str) -> Optional[bytes]:
        import base64

        padding = "=" * ((4 - len(raw) % 4) % 4)
        try:
            return base64.urlsafe_b64decode(raw + padding)
        except Exception:
            return None

    @contextmanager
    def _install_lock(self, request_id: str, product: str) -> Iterator[None]:
        lock_path = self.settings.lock_file
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + max(1, self.settings.install_lock_timeout_seconds)
        with lock_path.open("a+", encoding="utf-8") as handle:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if time.time() >= deadline:
                        raise TimeoutError(
                            f"install lock timeout for product={product} request_id={request_id} file={lock_path}"
                        )
                    time.sleep(0.2)
            try:
                handle.seek(0)
                handle.truncate(0)
                handle.write(
                    f"request_id={request_id}\nproduct={product}\npid={os.getpid()}\nacquired_at={now_utc()}\n"
                )
                handle.flush()
                yield
            finally:
                try:
                    handle.seek(0)
                    handle.truncate(0)
                    handle.flush()
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
