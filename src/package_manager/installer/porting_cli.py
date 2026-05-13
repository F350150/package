"""Porting CLI 安装器实现。"""

import shutil

from package_manager.constants import PKG_FMT_RPM, PRODUCT_PORTING_CLI
from package_manager.errors import InstallError
from package_manager.paths import internal_dir, root_ca_path
from package_manager.resolver import build_project_base_url
from package_manager.verifier import verify_p7s_detached

from .base import PreCheckResult, RpmInstaller
from .utils import ensure_local_or_download, resolve_install_dir, run_rpm_command


class PortingCliRpmInstaller(RpmInstaller):
    """Porting CLI rpm 安装器。"""

    def _framework_filename(self) -> str:
        return self.resolved.filename.replace("devkit-porting-", "devkit-", 1)

    def _framework_signature_url(self) -> str:
        return f"{self._framework_package_url()}{self.download_defaults.signature_suffix}"

    def _framework_package_url(self) -> str:
        project_base = build_project_base_url(self.download_defaults.base_url, self.resolved.config.version)
        return f"{project_base}/{self._framework_filename()}"

    def _framework_package_path(self):
        return self.resolved.package_path.parent / self._framework_filename()

    def _framework_signature_path(self):
        return self.resolved.package_path.parent / f"{self._framework_filename()}{self.download_defaults.signature_suffix}"

    def pre_check(self, installed_version):
        install_dir = resolve_install_dir(self.resolved)
        ready = (install_dir / "DevKit-Porting-CLI" / "devkit").exists()
        if installed_version == self.resolved.config.version and ready:
            return PreCheckResult(should_install=False, reason=f"same version installed: {installed_version}")
        return PreCheckResult(should_install=True)

    def remove_previous_version(self, installed_version: str) -> None:
        super().remove_previous_version(installed_version)
        porting_root = resolve_install_dir(self.resolved)
        if porting_root.exists():
            shutil.rmtree(porting_root, ignore_errors=True)

    def download(self) -> None:
        super().download()
        ensure_local_or_download(
            self._framework_package_url(),
            self._framework_package_path(),
            self.download_defaults.timeout_seconds,
            self.download_defaults.retry,
        )
        ensure_local_or_download(
            self._framework_signature_url(),
            self._framework_signature_path(),
            self.download_defaults.timeout_seconds,
            self.download_defaults.retry,
        )

    def verify_signature(self) -> None:
        super().verify_signature()
        verify_p7s_detached(
            package_path=self._framework_package_path(),
            signature_path=self._framework_signature_path(),
            root_ca=root_ca_path(),
            signature_format=self.verify_defaults.signature_format,
            verify_chain=self.verify_defaults.verify_chain,
        )

    def install(self) -> None:
        target_root = str(internal_dir())
        for pkg_path in [self._framework_package_path(), self.resolved.package_path]:
            result = run_rpm_command(["-Uvh", "--replacepkgs", str(pkg_path), "--relocate", f"/usr/local={target_root}"])
            if result.returncode != 0:
                raise InstallError(f"rpm install failed: {result.stderr.strip()}")

        devkit_dir = internal_dir() / "devkit"
        porting_root = resolve_install_dir(self.resolved)
        try:
            porting_root.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise InstallError(f"Failed to prepare porting root directory {porting_root}: {exc}") from exc
        target = porting_root / "DevKit-Porting-CLI"
        if target.exists():
            try:
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink(missing_ok=True)
            except Exception as exc:
                raise InstallError(f"Failed to clean existing target {target}: {exc}") from exc
        if not devkit_dir.exists():
            raise InstallError(f"Expected relocated directory missing after rpm install: {devkit_dir}")
        try:
            devkit_dir.rename(target)
        except Exception as exc:
            raise InstallError(f"Failed to move {devkit_dir} to {target}: {exc}") from exc

    def cache_artifacts_to_keep(self):
        return (
            self.resolved.package_path,
            self.resolved.signature_path,
            self._framework_package_path(),
            self._framework_signature_path(),
        )


REGISTER = {
    (PRODUCT_PORTING_CLI, PKG_FMT_RPM): PortingCliRpmInstaller,
}
