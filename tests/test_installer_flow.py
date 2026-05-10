from pathlib import Path

import pytest

from package_manager.errors import DownloadError, InstallError, SignatureVerifyError
from package_manager.models import DownloadDefaults, PackageConfig, ResolvedPackage, VerifyDefaults
from package_manager.installers import BaseInstaller, PreCheckResult


class DummyInstaller(BaseInstaller):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.install_called = False
        self.rollback_called = False
        self.remove_previous_called = False
        self.precheck_result = PreCheckResult(should_install=True)

    def pre_check(self, installed_version):
        return self.precheck_result

    def remove_previous_version(self, installed_version: str) -> None:
        self.remove_previous_called = True

    def install(self) -> None:
        self.install_called = True

    def rollback(self) -> None:
        self.rollback_called = True


def _resolved(tmp_path: Path) -> ResolvedPackage:
    cfg = PackageConfig(
        product="tiancheng",
        version="1",
        artifact_version="1",
        package_format="tar.gz",
        install_dir="_internal/products/tiancheng",
    )
    package_dir = tmp_path / "downloads" / cfg.product
    package_dir.mkdir(parents=True)
    package_path = package_dir / "a.tar.gz"
    sig_path = package_dir / "a.tar.gz.p7s"
    return ResolvedPackage(
        config=cfg,
        runtime_arch="x86_64",
        filename="a.tar.gz",
        package_url="http://x/a.tar.gz",
        signature_url="http://x/a.tar.gz.p7s",
        package_path=package_path,
        signature_path=sig_path,
    )


def _installer(tmp_path: Path) -> DummyInstaller:
    return DummyInstaller(
        _resolved(tmp_path),
        DownloadDefaults(base_url="http://x"),
        VerifyDefaults(),
    )


def test_run_success(monkeypatch, tmp_path):
    inst = _installer(tmp_path)

    monkeypatch.setattr("package_manager.installers.download_file", lambda *a, **k: None)
    monkeypatch.setattr("package_manager.installers.verify_p7s_detached", lambda *a, **k: None)
    monkeypatch.setattr("package_manager.installers.root_ca_path", lambda: tmp_path / "ca.pem")
    monkeypatch.setattr("package_manager.installers.update_install_state", lambda **kwargs: None)

    inst.run()
    assert inst.install_called is True


def test_download_failure_cleanup(monkeypatch, tmp_path):
    inst = _installer(tmp_path)

    def fail_download(*a, **k):
        raise DownloadError("d")

    monkeypatch.setattr("package_manager.installers.download_file", fail_download)
    monkeypatch.setattr("package_manager.installers.verify_p7s_detached", lambda *a, **k: None)
    monkeypatch.setattr("package_manager.installers.root_ca_path", lambda: tmp_path / "ca.pem")
    monkeypatch.setattr("package_manager.installers.update_install_state", lambda **kwargs: None)

    with pytest.raises(DownloadError):
        inst.run()

    assert inst.install_called is False
    assert inst.rollback_called is True
    assert not inst.resolved.package_path.parent.exists()


def test_signature_failure_no_install(monkeypatch, tmp_path):
    inst = _installer(tmp_path)

    monkeypatch.setattr("package_manager.installers.download_file", lambda *a, **k: None)

    def fail_sig(*a, **k):
        raise SignatureVerifyError("s")

    monkeypatch.setattr("package_manager.installers.verify_p7s_detached", fail_sig)
    monkeypatch.setattr("package_manager.installers.root_ca_path", lambda: tmp_path / "ca.pem")
    monkeypatch.setattr("package_manager.installers.update_install_state", lambda **kwargs: None)

    with pytest.raises(SignatureVerifyError):
        inst.run()

    assert inst.install_called is False
    assert inst.rollback_called is True


def test_install_failure_rollback_and_cleanup(monkeypatch, tmp_path):
    inst = _installer(tmp_path)

    def fail_install():
        raise InstallError("install failed")

    inst.install = fail_install

    monkeypatch.setattr("package_manager.installers.download_file", lambda *a, **k: None)
    monkeypatch.setattr("package_manager.installers.verify_p7s_detached", lambda *a, **k: None)
    monkeypatch.setattr("package_manager.installers.root_ca_path", lambda: tmp_path / "ca.pem")
    monkeypatch.setattr("package_manager.installers.update_install_state", lambda **kwargs: None)

    with pytest.raises(InstallError):
        inst.run()

    assert inst.rollback_called is True
    assert not inst.resolved.package_path.parent.exists()


def test_version_switch_calls_remove_previous(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    monkeypatch.setattr("package_manager.installers.get_installed_version", lambda _p: "0.9")
    monkeypatch.setattr("package_manager.installers.download_file", lambda *a, **k: None)
    monkeypatch.setattr("package_manager.installers.verify_p7s_detached", lambda *a, **k: None)
    monkeypatch.setattr("package_manager.installers.root_ca_path", lambda: tmp_path / "ca.pem")
    monkeypatch.setattr("package_manager.installers.update_install_state", lambda **kwargs: None)

    inst.run()
    assert inst.remove_previous_called is True
    assert inst.install_called is True


def test_precheck_skip_does_not_install(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.precheck_result = PreCheckResult(should_install=False, reason="already installed")
    state_calls = []
    monkeypatch.setattr("package_manager.installers.update_install_state", lambda **kwargs: state_calls.append(kwargs))

    inst.run()
    assert inst.install_called is False
    assert len(state_calls) == 1


def test_download_uses_local_files_without_network(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.resolved.package_path.write_bytes(b"pkg")
    inst.resolved.signature_path.write_bytes(b"sig")
    download_calls = []
    monkeypatch.setattr("package_manager.installers.download_file", lambda *a, **k: download_calls.append((a, k)))
    monkeypatch.setattr("package_manager.installers.verify_p7s_detached", lambda *a, **k: None)
    monkeypatch.setattr("package_manager.installers.root_ca_path", lambda: tmp_path / "ca.pem")
    monkeypatch.setattr("package_manager.installers.update_install_state", lambda **kwargs: None)

    inst.run()

    assert inst.install_called is True
    assert download_calls == []


def test_download_failure_contains_offline_hint(monkeypatch, tmp_path):
    inst = _installer(tmp_path)

    def fail_download(*_a, **_k):
        raise DownloadError("network down")

    monkeypatch.setattr("package_manager.installers.download_file", fail_download)
    monkeypatch.setattr("package_manager.installers.verify_p7s_detached", lambda *a, **k: None)
    monkeypatch.setattr("package_manager.installers.root_ca_path", lambda: tmp_path / "ca.pem")
    monkeypatch.setattr("package_manager.installers.update_install_state", lambda **kwargs: None)

    with pytest.raises(DownloadError) as excinfo:
        inst.run()

    message = str(excinfo.value)
    assert "Offline install hint" in message
    assert str(inst.resolved.package_path) in message
