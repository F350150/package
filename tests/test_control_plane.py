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
        config_lock_file=tmp_path / ".package-manager" / ".mcp_config.lock",
        uninstall_lock_file=tmp_path / ".package-manager" / ".mcp_uninstall.lock",
        confirm_lock_file=tmp_path / ".package-manager" / ".mcp_confirm.lock",
        confirm_used_file=tmp_path / ".package-manager" / ".mcp_confirm_used.json",
        idempotency_file=tmp_path / ".package-manager" / ".mcp_idempotency.json",
        audit_file=tmp_path / ".package-manager" / "audit.log",
        config_backup_dir=tmp_path / ".package-manager" / "config-backups",
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


def test_install_with_guardrails_fallback_when_dry_run_flag_not_supported(tmp_path: Path):
    config = tmp_path / "packages.yaml"
    state = tmp_path / ".package-manager" / ".install_state.yaml"
    binary = tmp_path / "package-manager"
    _write_config(config)
    _write_state(state)
    binary.write_text(
        """#!/usr/bin/env python3
import sys
if "--help" in sys.argv:
    print("usage: package-manager --name <product>")
    raise SystemExit(0)
if "--dry-run" in sys.argv:
    print("package-manager: error: unrecognized arguments: --dry-run", file=sys.stderr)
    raise SystemExit(2)
print("Installer run completed: demo-product")
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    binary.chmod(0o755)

    cp = PackageManagerControlPlane(
        settings=ControlPlaneSettings(
            binary_path=binary,
            config_file=config,
            state_file=state,
            command_timeout_seconds=120,
            lock_file=tmp_path / ".package-manager" / ".mcp_install.lock",
            dry_run_mode="command",
        )
    )

    result = cp.install_with_guardrails("demo-product")
    assert result["status"] == "success"
    phases = result["phases"]
    assert phases["dry_run"]["status"] == "success"
    assert phases["dry_run"]["dry_run_mode"] == "simulate_fallback"
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


def test_get_config_supports_path_and_product(tmp_path: Path):
    cp = _control_plane(tmp_path)
    by_path = cp.get_config(path="download_defaults.base_url")
    assert by_path["status"] == "success"
    assert by_path["value"] == "https://example.com/demo/"
    by_product = cp.get_config(product="demo-product")
    assert by_product["status"] == "success"
    assert by_product["value"]["artifact_version"] == "1.0.1"


def test_update_config_plan_confirm_apply_and_rollback(tmp_path: Path):
    cp = _control_plane(tmp_path)
    plan = cp.update_config_plan(
        operations=[{"op": "set", "path": "packages[demo-product].enabled", "value": False}],
        actor="tester",
        reason="disable for maintenance",
    )
    assert plan["status"] == "success"
    plan_id = plan["plan_id"]
    confirm = cp.confirm_plan(plan_id=plan_id, actor="tester")
    assert confirm["status"] == "success"
    apply_result = cp.update_config_apply(
        plan_id=plan_id,
        challenge_token=confirm["challenge_token"],
        request_id="req-config-apply-1",
        idempotency_key="idem-config-1",
        actor="tester",
    )
    assert apply_result["status"] == "success"
    assert apply_result["config_backup_version"].startswith("config-")

    read_back = cp.get_config(path="packages[demo-product].enabled")
    assert read_back["value"] is False

    rollback = cp.rollback_config(
        version_id=apply_result["config_backup_version"],
        request_id="req-config-rollback-1",
        idempotency_key="idem-config-rollback-1",
        actor="tester",
    )
    assert rollback["status"] == "success"
    restored = cp.get_config(path="packages[demo-product].enabled")
    assert restored["value"] is True


def test_update_config_allows_project_version_when_supported_versions_match(tmp_path: Path):
    cp = _control_plane(tmp_path)
    plan = cp.update_config_plan(
        operations=[
            {"op": "set", "path": "packages[demo-product].project_version", "value": "1.0.1"},
            {"op": "set", "path": "packages[demo-product].supported_versions", "value": ["1.0.0", "1.0.1"]},
        ],
        actor="tester",
    )
    assert plan["status"] == "success"


def test_confirm_token_replay_is_blocked(tmp_path: Path):
    cp = _control_plane(tmp_path)
    plan = cp.update_config_plan(
        operations=[{"op": "set", "path": "download_defaults.retry", "value": 5}],
        actor="tester",
    )
    confirm = cp.confirm_plan(plan_id=plan["plan_id"], actor="tester")
    first = cp.update_config_apply(
        plan_id=plan["plan_id"],
        challenge_token=confirm["challenge_token"],
        request_id="req-replay-1",
        idempotency_key="idem-replay-1",
        actor="tester",
    )
    assert first["status"] == "success"
    second = cp.update_config_apply(
        plan_id=plan["plan_id"],
        challenge_token=confirm["challenge_token"],
        request_id="req-replay-2",
        idempotency_key="idem-replay-2",
        actor="tester",
    )
    assert second["status"] == "error"
    assert second["error_code"] == "confirm_replayed"


def test_uninstall_plan_confirm_apply(tmp_path: Path):
    cp = _control_plane(tmp_path)
    install_root = cp.settings.binary_path.parent
    target_dir = install_root / "_internal" / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "payload.txt").write_text("ok", encoding="utf-8")

    plan = cp.uninstall_plan(product="demo-product", actor="tester")
    assert plan["status"] == "success"
    assert plan["plan"]["target_path_exists"] is True
    confirm = cp.confirm_plan(plan_id=plan["plan_id"], actor="tester")
    assert confirm["status"] == "success"
    applied = cp.uninstall_apply(
        plan_id=plan["plan_id"],
        challenge_token=confirm["challenge_token"],
        request_id="req-uninstall-1",
        idempotency_key="idem-uninstall-1",
        actor="tester",
    )
    assert applied["status"] == "success"
    assert not target_dir.exists()
    status = cp.status(product="demo-product")
    assert status["state"] is None


def test_offline_manifest_and_artifact_check(tmp_path: Path):
    cp = _control_plane(tmp_path)
    manifest = cp.offline_manifest("demo-product")
    assert manifest["status"] == "success"
    assert manifest["filename"].startswith("demo-product-")
    pkg_path = Path(manifest["remote_package_path"])
    sig_path = Path(manifest["remote_signature_path"])
    if pkg_path.exists():
        pkg_path.unlink()
    if sig_path.exists():
        sig_path.unlink()
    check0 = cp.check_offline_artifacts("demo-product")
    assert check0["ready_for_offline_install"] is False
    pkg_path.parent.mkdir(parents=True, exist_ok=True)
    pkg_path.write_bytes(b"pkg")
    sig_path.write_bytes(b"sig")
    check1 = cp.check_offline_artifacts("demo-product")
    assert check1["ready_for_offline_install"] is True


def test_probe_network_recommends_online(monkeypatch, tmp_path: Path):
    cp = _control_plane(tmp_path)

    class _Sock:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("package_manager.control_plane.socket.create_connection", lambda *_a, **_k: _Sock())
    monkeypatch.setattr("package_manager.control_plane.get_remote_file_size", lambda *_a, **_k: 1234)
    result = cp.probe_network_for_product("demo-product", timeout_seconds=2)
    assert result["recommended_mode"] == "online"


def test_probe_network_recommends_offline(monkeypatch, tmp_path: Path):
    cp = _control_plane(tmp_path)

    def _fail(*_a, **_k):
        raise OSError("network blocked")

    monkeypatch.setattr("package_manager.control_plane.socket.create_connection", _fail)
    monkeypatch.setattr("package_manager.control_plane.get_remote_file_size", lambda *_a, **_k: None)
    result = cp.probe_network_for_product("demo-product", timeout_seconds=2)
    assert result["recommended_mode"] == "offline"


def test_offline_stage_and_install_routes_online(monkeypatch, tmp_path: Path):
    cp = _control_plane(tmp_path)
    monkeypatch.setattr(
        cp,
        "probe_network_for_product",
        lambda product, timeout_seconds=5: {
            "status": "success",
            "product": product,
            "recommended_mode": "online",
        },
    )
    monkeypatch.setattr(cp, "install_with_guardrails", lambda product: {"status": "success", "product": product})
    monkeypatch.setattr(cp, "status", lambda product=None: {"status": "success", "product": product, "state": {}})
    result = cp.offline_stage_and_install(product="demo-product")
    assert result["status"] == "success"
    assert result["executed_mode"] == "online"
    assert result["phases"]["install"]["status"] == "success"


def test_offline_stage_and_install_routes_offline(monkeypatch, tmp_path: Path):
    cp = _control_plane(tmp_path)
    monkeypatch.setattr(
        cp,
        "probe_network_for_product",
        lambda product, timeout_seconds=5: {
            "status": "success",
            "product": product,
            "recommended_mode": "offline",
        },
    )
    monkeypatch.setattr(
        cp,
        "offline_manifest",
        lambda product: {
            "status": "success",
            "product": product,
            "package_url": "https://example.com/a.tar.gz",
            "signature_url": "https://example.com/a.tar.gz.p7s",
            "remote_package_path": str(tmp_path / "_internal" / "packages" / "demo-product" / "a.tar.gz"),
            "remote_signature_path": str(tmp_path / "_internal" / "packages" / "demo-product" / "a.tar.gz.p7s"),
        },
    )
    monkeypatch.setattr(cp, "_stage_offline_artifacts", lambda **_kwargs: {"status": "success", "exit_code": 0})
    monkeypatch.setattr(
        cp,
        "check_offline_artifacts",
        lambda product: {"status": "success", "product": product, "ready_for_offline_install": True},
    )
    monkeypatch.setattr(cp, "install_with_guardrails", lambda product: {"status": "success", "product": product})
    monkeypatch.setattr(cp, "status", lambda product=None: {"status": "success", "product": product, "state": {}})
    result = cp.offline_stage_and_install(product="demo-product", docker_container="openeuler-arm-mcp")
    assert result["status"] == "success"
    assert result["executed_mode"] == "offline"
    assert result["phases"]["stage_upload"]["status"] == "success"
