import fcntl
import time
from pathlib import Path

import pytest

from package_manager.control_plane import ControlPlaneSettings, PackageManagerControlPlane


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
  - product: "disabled-product"
    project_version: "1.0.0"
    artifact_version: "1.0.2"
    package_format: "tar.gz"
    install_dir: "_internal/demo2"
    enabled: false
    supported_versions: ["1.0.0"]
""".strip(),
        encoding="utf-8",
    )


def _write_fake_binary(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import sys
import time

if "--help" in sys.argv:
    print("usage: package-manager --name <product>")
    raise SystemExit(0)

name = None
if "--name" in sys.argv:
    idx = sys.argv.index("--name")
    if idx + 1 < len(sys.argv):
        name = sys.argv[idx + 1]

if "--sleep-seconds" in sys.argv:
    idx = sys.argv.index("--sleep-seconds")
    if idx + 1 < len(sys.argv):
        time.sleep(float(sys.argv[idx + 1]))

if name == "bad-product":
    print("Installer error: bad product", file=sys.stderr)
    raise SystemExit(10)

print(f"Installer run completed: {name}")
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


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


def _control_plane(tmp_path: Path) -> PackageManagerControlPlane:
    config = tmp_path / "packages.yaml"
    state = tmp_path / ".package-manager" / ".install_state.yaml"
    binary = tmp_path / "package-manager"
    _write_config(config)
    _write_state(state)
    _write_fake_binary(binary)
    settings = ControlPlaneSettings(
        binary_path=binary,
        config_file=config,
        state_file=state,
        command_timeout_seconds=120,
        lock_file=tmp_path / ".package-manager" / ".mcp_install.lock",
    )
    return PackageManagerControlPlane(settings=settings)


def test_list_packages_only_enabled(tmp_path: Path):
    cp = _control_plane(tmp_path)
    result = cp.list_packages()
    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["packages"][0]["product"] == "demo-product"


def test_status_all_and_single_product(tmp_path: Path):
    cp = _control_plane(tmp_path)
    all_status = cp.status()
    assert "demo-product" in all_status["products"]
    single = cp.status(product="demo-product")
    assert single["state"]["installed_version"] == "1.0.0"


def test_health_success(tmp_path: Path):
    cp = _control_plane(tmp_path)
    result = cp.health()
    assert result["healthy"] is True
    assert result["binary_help_exit_code"] == 0


def test_install_dry_run(tmp_path: Path):
    cp = _control_plane(tmp_path)
    result = cp.install("demo-product", dry_run=True)
    assert result["status"] == "success"
    assert result["dry_run"] is True
    assert result["dry_run_mode"] == "command"
    assert result["exit_code"] == 0
    assert "Installer run completed" in result["output_tail"]


def test_install_success(tmp_path: Path):
    cp = _control_plane(tmp_path)
    result = cp.install("demo-product", dry_run=False)
    assert result["status"] == "success"
    assert result["exit_code"] == 0
    assert "Installer run completed" in result["output_tail"]


def test_install_unknown_product_raises(tmp_path: Path):
    cp = _control_plane(tmp_path)
    with pytest.raises(ValueError, match="unknown or disabled product"):
        cp.install("not-exist", dry_run=False)


def test_install_with_guardrails_success(tmp_path: Path):
    cp = _control_plane(tmp_path)
    result = cp.install_with_guardrails("demo-product")
    assert result["status"] == "success"
    phases = result["phases"]
    assert phases["health"]["healthy"] is True
    assert phases["dry_run"]["status"] == "success"
    assert phases["install"]["status"] == "success"


def test_install_respects_lock_timeout(tmp_path: Path):
    config = tmp_path / "packages.yaml"
    state = tmp_path / ".package-manager" / ".install_state.yaml"
    binary = tmp_path / "package-manager"
    lock_file = tmp_path / ".package-manager" / ".mcp_install.lock"
    _write_config(config)
    _write_state(state)
    _write_fake_binary(binary)
    settings = ControlPlaneSettings(
        binary_path=binary,
        config_file=config,
        state_file=state,
        command_timeout_seconds=120,
        lock_file=lock_file,
        install_lock_timeout_seconds=1,
    )
    cp = PackageManagerControlPlane(settings=settings)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        started = time.time()
        result = cp.install("demo-product", dry_run=False)
        elapsed = time.time() - started
        assert elapsed >= 1.0
        assert result["status"] == "error"
        assert result["error_code"] == "lock_timeout"
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def test_install_handles_command_timeout(tmp_path: Path):
    binary = tmp_path / "sleeping-binary"
    binary.write_text(
        """#!/usr/bin/env python3
import sys
import time
if "--help" in sys.argv:
    print("usage: package-manager --name <product>")
    raise SystemExit(0)
time.sleep(2.5)
print("slow install done")
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    config = tmp_path / "packages.yaml"
    state = tmp_path / ".package-manager" / ".install_state.yaml"
    _write_config(config)
    _write_state(state)
    cp = PackageManagerControlPlane(
        settings=ControlPlaneSettings(
            binary_path=binary,
            config_file=config,
            state_file=state,
            command_timeout_seconds=1,
            lock_file=tmp_path / ".package-manager" / ".mcp_install.lock",
        )
    )
    result = cp.install("demo-product", dry_run=False)
    assert result["status"] == "error"
    assert result["error_code"] == "command_timeout"
