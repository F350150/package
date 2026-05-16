"""Package manager control-plane adapter for MCP tools."""

from __future__ import annotations

import errno
import fcntl
import os
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from package_manager.config import RuntimeConfig, load_runtime_config_from_path
from package_manager.install_state import load_install_state


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def tail_lines(text: str, limit: int = 80) -> str:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if len(lines) <= limit:
        return "\n".join(lines)
    return "\n".join(lines[-limit:])


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
        return cls(
            binary_path=binary_path,
            config_file=config_file,
            state_file=state_file,
            command_timeout_seconds=timeout,
            lock_file=lock_file,
            install_lock_timeout_seconds=lock_timeout,
            dry_run_mode=dry_run_mode,
        )


class PackageManagerControlPlane:
    """Whitelist actions used by MCP tools."""

    def __init__(self, settings: ControlPlaneSettings):
        self.settings = settings

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
