from pathlib import Path

from package_manager.models import DownloadDefaults, PackageConfig
from package_manager.resolver import resolve_package


def test_resolve_package_builds_urls_and_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("package_manager.resolver.download_dir", lambda: tmp_path / "downloads")
    monkeypatch.setattr("package_manager.resolver.detect_runtime_arch", lambda: "x86_64")

    defaults = DownloadDefaults(base_url="https://example.com/packages", signature_suffix=".p7s")
    pkg = PackageConfig(
        product="tiancheng",
        version="1.0",
        package_format="tar.gz",
    )

    resolved = resolve_package(pkg, defaults)
    expected_filename = "tiancheng-1.0-Linux-x86-64.tar.gz"
    assert resolved.package_url == f"https://example.com/packages/{expected_filename}"
    assert resolved.signature_url == f"https://example.com/packages/{expected_filename}.p7s"
    assert resolved.package_id == "tiancheng-linux-x86_64-tar-gz"
    assert resolved.package_path == tmp_path / "downloads" / "tiancheng-linux-x86_64-tar-gz" / expected_filename
    assert resolved.signature_path == tmp_path / "downloads" / "tiancheng-linux-x86_64-tar-gz" / f"{expected_filename}.p7s"


def test_resolve_rpm_filename_for_arm(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("package_manager.resolver.download_dir", lambda: tmp_path / "downloads")
    monkeypatch.setattr("package_manager.resolver.detect_runtime_arch", lambda: "arm64")

    defaults = DownloadDefaults(base_url="https://example.com/packages", signature_suffix=".p7s")
    pkg = PackageConfig(product="tiancheng", version="2.0", package_format="rpm")

    resolved = resolve_package(pkg, defaults)
    assert resolved.filename == "tiancheng-2.0-aarch64.rpm"
    assert resolved.package_id == "tiancheng-linux-arm64-rpm"
