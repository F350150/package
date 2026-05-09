from pathlib import Path

from package_manager.installers import PortingCliRpmInstaller
from package_manager.models import DownloadDefaults, PackageConfig, ResolvedPackage, VerifyDefaults


def test_porting_cli_framework_url_uses_project_version(tmp_path: Path):
    cfg = PackageConfig(
        product="devkit-porting",
        version="26.0.RC2",
        artifact_version="26.0.rc1-1",
        package_format="rpm",
        rpm_arch_separator=".",
    )
    package_id = "devkit-porting-linux-arm64-rpm"
    filename = "devkit-porting-26.0.rc1-1.aarch64.rpm"
    package_dir = tmp_path / "downloads" / package_id
    package_dir.mkdir(parents=True)
    resolved = ResolvedPackage(
        config=cfg,
        package_id=package_id,
        runtime_arch="arm64",
        filename=filename,
        package_url=f"https://example.com/base/26.0.RC2/{filename}",
        signature_url=f"https://example.com/base/26.0.RC2/{filename}.p7s",
        package_path=package_dir / filename,
        signature_path=package_dir / f"{filename}.p7s",
    )

    installer = PortingCliRpmInstaller(
        resolved,
        DownloadDefaults(base_url="https://example.com/base/", signature_suffix=".p7s"),
        VerifyDefaults(),
    )

    assert installer._framework_package_url() == "https://example.com/base/26.0.RC2/devkit-26.0.rc1-1.aarch64.rpm"
    assert installer._framework_signature_url() == "https://example.com/base/26.0.RC2/devkit-26.0.rc1-1.aarch64.rpm.p7s"
