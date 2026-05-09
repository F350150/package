from pathlib import Path

from package_manager.models import DownloadDefaults, PackageConfig
from package_manager.resolver import resolve_package


def test_resolve_package_builds_urls_and_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("package_manager.resolver.download_dir", lambda: tmp_path / "downloads")
    monkeypatch.setattr("package_manager.resolver.detect_runtime_arch", lambda: "x86_64")

    defaults = DownloadDefaults(base_url="https://example.com/packages/", signature_suffix=".p7s")
    pkg = PackageConfig(
        product="tiancheng",
        version="1.0",
        artifact_version="1.0.7",
        package_format="tar.gz",
    )

    resolved = resolve_package(pkg, defaults)
    expected_filename = "tiancheng-1.0.7-Linux-x86-64.tar.gz"
    assert resolved.package_url == f"https://example.com/packages/1.0/{expected_filename}"
    assert resolved.signature_url == f"https://example.com/packages/1.0/{expected_filename}.p7s"
    assert resolved.package_id == "tiancheng-linux-x86_64-tar-gz"
    assert resolved.package_path == tmp_path / "downloads" / "tiancheng-linux-x86_64-tar-gz" / expected_filename
    assert resolved.signature_path == tmp_path / "downloads" / "tiancheng-linux-x86_64-tar-gz" / f"{expected_filename}.p7s"


def test_resolve_rpm_filename_for_arm(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("package_manager.resolver.download_dir", lambda: tmp_path / "downloads")
    monkeypatch.setattr("package_manager.resolver.detect_runtime_arch", lambda: "arm64")

    defaults = DownloadDefaults(base_url="https://example.com/packages/", signature_suffix=".p7s")
    pkg = PackageConfig(product="tiancheng", version="2.0.RC1", artifact_version="2.0.rc1-1", package_format="rpm")

    resolved = resolve_package(pkg, defaults)
    assert resolved.filename == "tiancheng-2.0.rc1-1-aarch64.rpm"
    assert resolved.package_url == "https://example.com/packages/2.0.RC1/tiancheng-2.0.rc1-1-aarch64.rpm"
    assert resolved.package_id == "tiancheng-linux-arm64-rpm"


def test_resolve_rpm_filename_with_dot_separator(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("package_manager.resolver.download_dir", lambda: tmp_path / "downloads")
    monkeypatch.setattr("package_manager.resolver.detect_runtime_arch", lambda: "arm64")

    defaults = DownloadDefaults(base_url="https://example.com/packages/", signature_suffix=".p7s")
    pkg = PackageConfig(
        product="devkit-porting",
        version="26.0.RC1",
        artifact_version="26.0.rc1-1",
        package_format="rpm",
        rpm_arch_separator=".",
    )

    resolved = resolve_package(pkg, defaults)
    assert resolved.filename == "devkit-porting-26.0.rc1-1.aarch64.rpm"
    assert resolved.package_url == "https://example.com/packages/26.0.RC1/devkit-porting-26.0.rc1-1.aarch64.rpm"


def test_resolve_porting_advisor_uses_filename_product_token(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("package_manager.resolver.download_dir", lambda: tmp_path / "downloads")
    monkeypatch.setattr("package_manager.resolver.detect_runtime_arch", lambda: "arm64")

    defaults = DownloadDefaults(base_url="https://example.com/packages/", signature_suffix=".p7s")
    pkg = PackageConfig(
        product="Porting-Advisor",
        version="26.0.RC2",
        artifact_version="26.0.RC1",
        package_format="tar.gz",
    )

    resolved = resolve_package(pkg, defaults)
    assert resolved.filename == "DevKit-Porting-Advisor-26.0.RC1-Linux-Kunpeng.tar.gz"
    assert (
        resolved.package_url
        == "https://example.com/packages/26.0.RC2/DevKit-Porting-Advisor-26.0.RC1-Linux-Kunpeng.tar.gz"
    )
    assert resolved.package_id == "Porting-Advisor-linux-arm64-tar-gz"
