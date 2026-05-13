"""Porting Advisor 安装器实现。"""

import shutil

from package_manager.constants import PKG_FMT_TAR_GZ, PRODUCT_PORTING_ADVISOR
from package_manager.errors import InstallError

from .base import PreCheckResult, TarGzInstaller
from .utils import (
    detect_porting_advisor_payload_dir,
    extract_tar_package,
    first_child_dir,
    first_match,
    has_porting_advisor_runtime_layout,
    install_porting_advisor_runtime_layout,
    reset_install_dir,
    resolve_install_dir,
)


class PortingAdvisorTarGzInstaller(TarGzInstaller):
    """Porting Advisor 安装器。"""

    def pre_check(self, installed_version):
        install_dir = resolve_install_dir(self.resolved)
        ready = has_porting_advisor_runtime_layout(install_dir)
        if installed_version == self.resolved.config.version and ready:
            return PreCheckResult(should_install=False, reason=f"same version installed: {installed_version}")
        return PreCheckResult(should_install=True)

    def install(self) -> None:
        install_dir = resolve_install_dir(self.resolved)
        reset_install_dir(install_dir)

        stage_dir = self.resolved.package_path.parent / "_extract_porting_advisor"
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        stage_dir.mkdir(parents=True, exist_ok=True)

        extract_tar_package(self.resolved.package_path, stage_dir)
        level1 = first_child_dir(stage_dir)
        nested_tar = first_match(level1, "*.tar.gz")
        extract_tar_package(nested_tar, level1)
        payload_dir = detect_porting_advisor_payload_dir(level1)
        install_porting_advisor_runtime_layout(payload_dir, install_dir)

    def post_install_check(self) -> None:
        install_dir = resolve_install_dir(self.resolved)
        if has_porting_advisor_runtime_layout(install_dir):
            return
        raise InstallError(f"{PRODUCT_PORTING_ADVISOR} install validation failed under {install_dir}")


REGISTER = {
    (PRODUCT_PORTING_ADVISOR, PKG_FMT_TAR_GZ): PortingAdvisorTarGzInstaller,
}
