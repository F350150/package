import os
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError as exc:
            pytest.skip(f"socket bind is not permitted in current environment: {exc}")
        return int(sock.getsockname()[1])


def _write_config(path: Path) -> None:
    path.write_text(
        """
download_defaults:
  base_url: "https://example.com/demo/"
verify_defaults:
  signature_type: "p7s"
  signature_format: "DER"
  verify_chain: true
packages:
  - product: "demo-product"
    project_version: "1.0.0"
    artifact_version: "1.0.1"
    package_format: "tar.gz"
    install_dir: "_internal/demo"
    enabled: true
    supported_versions: ["1.0.0"]
""".strip(),
        encoding="utf-8",
    )


def _write_state(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
products:
  demo-product:
    installed_version: "1.0.0"
    installed_at: "2026-05-16T11:20:02.049417+00:00"
    package_format: "tar.gz"
    last_result: "success"
""".strip(),
        encoding="utf-8",
    )


def _write_fake_binary(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import sys

if "--help" in sys.argv:
    print("usage: package-manager --name <product>")
    raise SystemExit(0)

name = None
if "--name" in sys.argv:
    idx = sys.argv.index("--name")
    if idx + 1 < len(sys.argv):
        name = sys.argv[idx + 1]

print(f"Installer run completed: {name}")
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


async def _exercise_mcp(url: str) -> None:
    async with streamable_http_client(url) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "pm_health",
                "pm_list_packages",
                "pm_status",
                "pm_install",
                "pm_skill_install_guarded",
                "pm_get_config",
                "pm_update_config_plan",
                "pm_update_config_apply",
                "pm_uninstall_plan",
                "pm_uninstall_apply",
                "pm_confirm_plan",
                "pm_rollback_config",
                "pm_probe_network",
                "pm_offline_manifest",
                "pm_check_offline_artifacts",
                "pm_offline_stage_and_install",
            }.issubset(names)

            list_result = await session.call_tool("pm_list_packages", {})
            assert list_result.isError is False
            list_payload = _tool_payload(list_result)
            assert list_payload["status"] == "success"
            assert list_payload["count"] == 1

            install_result = await session.call_tool("pm_install", {"product": "demo-product", "dry_run": True})
            assert install_result.isError is False
            install_payload = _tool_payload(install_result)
            assert install_payload["status"] == "success"
            assert install_payload["dry_run"] is True

            skill_result = await session.call_tool("pm_skill_install_guarded", {"product": "demo-product"})
            assert skill_result.isError is False
            skill_payload = _tool_payload(skill_result)
            assert skill_payload["status"] == "success"
            assert "phases" in skill_payload


def _tool_payload(tool_result):
    payload = tool_result.structuredContent
    if isinstance(payload, dict):
        if "result" in payload and isinstance(payload["result"], dict):
            return payload["result"]
        if "status" in payload:
            return payload
    for item in tool_result.content or []:
        text = getattr(item, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "result" in parsed and isinstance(parsed["result"], dict):
            return parsed["result"]
        if isinstance(parsed, dict):
            return parsed
    raise AssertionError(f"Unable to parse tool payload: {tool_result}")


def test_mcp_server_streamable_http_end_to_end(tmp_path: Path):
    config_file = tmp_path / "packages.yaml"
    state_file = tmp_path / ".package-manager" / ".install_state.yaml"
    binary_path = tmp_path / "package-manager"
    _write_config(config_file)
    _write_state(state_file)
    _write_fake_binary(binary_path)

    port = _free_port()
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["PACKAGE_MANAGER_INSTALL_LOCK_FILE"] = str(tmp_path / ".package-manager" / ".mcp_install.lock")
    cmd = [
        sys.executable,
        "-m",
        "package_manager.mcp_server",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--path",
        "/mcp",
        "--binary-path",
        str(binary_path),
        "--config-file",
        str(config_file),
        "--state-file",
        str(state_file),
        "--auth-disabled",
    ]
    proc = subprocess.Popen(cmd, cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        last_error = None
        time.sleep(0.6)
        for _ in range(10):
            if proc.poll() is not None:
                stdout, stderr = proc.communicate(timeout=2)
                raise AssertionError(
                    f"MCP server exited unexpectedly rc={proc.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )
            try:
                anyio.run(_exercise_mcp, url)
                return
            except Exception as exc:  # pragma: no cover - retry path
                last_error = exc
                time.sleep(0.4)
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=5)
        raise AssertionError(
            f"MCP E2E failed: {last_error!r}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:  # pragma: no cover - safety net
            proc.kill()
