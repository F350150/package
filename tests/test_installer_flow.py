from pathlib import Path

import pytest

from package_manager.errors import DownloadError, InstallError, SignatureVerifyError
from package_manager.models import DownloadDefaults, PackageConfig, ResolvedPackage, VerifyDefaults
from package_manager.installers import BaseInstaller


class DummyInstaller(BaseInstaller):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.install_called = False
        self.rollback_called = False

    def install(self) -> None:
        self.install_called = True

    def rollback(self) -> None:
        self.rollback_called = True


def _resolved(tmp_path: Path) -> ResolvedPackage:
    cfg = PackageConfig(
        product="tiancheng",
        version="1",
        package_format="tar.gz",
    )
    package_id = "tiancheng-linux-x86_64-tar-gz"
    package_dir = tmp_path / "downloads" / package_id
    package_dir.mkdir(parents=True)
    package_path = package_dir / "a.tar.gz"
    sig_path = package_dir / "a.tar.gz.p7s"
    return ResolvedPackage(
        config=cfg,
        package_id=package_id,
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

    inst.run()
    assert inst.install_called is True


def test_download_failure_cleanup(monkeypatch, tmp_path):
    inst = _installer(tmp_path)

    def fail_download(*a, **k):
        raise DownloadError("d")

    monkeypatch.setattr("package_manager.installers.download_file", fail_download)
    monkeypatch.setattr("package_manager.installers.verify_p7s_detached", lambda *a, **k: None)
    monkeypatch.setattr("package_manager.installers.root_ca_path", lambda: tmp_path / "ca.pem")

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

    with pytest.raises(InstallError):
        inst.run()

    assert inst.rollback_called is True
    assert not inst.resolved.package_path.parent.exists()
