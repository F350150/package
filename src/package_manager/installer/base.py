"""安装器基类与通用模板实现。"""

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from package_manager.constants import CACHE_POLICY_KEEP_LATEST
from package_manager.errors import CleanupError, InstallError, InstallerError
from package_manager.install_state import get_installed_version, update_install_state
from package_manager.models import DownloadDefaults, ResolvedPackage, VerifyDefaults
from package_manager.paths import root_ca_path
from package_manager.verifier import verify_p7s_detached

from . import utils


@dataclass(frozen=True)
class PreCheckResult:
    """安装前检查结果。"""

    should_install: bool
    reason: str = ""


class BaseInstaller(ABC):
    """安装流程模板父类。"""

    def __init__(self, resolved: ResolvedPackage, download_defaults: DownloadDefaults, verify_defaults: VerifyDefaults):
        self.resolved = resolved
        self.download_defaults = download_defaults
        self.verify_defaults = verify_defaults

    def run(self) -> None:
        """按固定模板执行安装。"""

        print(f"Installer run started: {self._log_identity()}")
        installed_version = self.recorded_installed_version()
        target_version = self.resolved.config.version
        if installed_version and installed_version != target_version:
            print(
                f"Detected version switch for {self.resolved.config.product}: "
                f"{installed_version} -> {target_version}"
            )
            self.remove_previous_version(installed_version)

        precheck = self.pre_check(installed_version)
        if not precheck.should_install:
            reason = precheck.reason or "already installed"
            print(f"Installer pre-check hit, skip installation: {self._log_identity()}, reason={reason}")
            self.record_install_success()
            return
        try:
            self.prepare()
            self.download()
            self.verify_signature()
            self.pre_install()
            self.install()
            self.post_install_check()
            self.cleanup_after_success()
            self.record_install_success()
            print(f"Installer run completed: {self._log_identity()}")
        except InstallerError:
            print(f"Installer run failed: {self._log_identity()}")
            self.rollback_safely()
            self.cleanup_temp_safely()
            raise
        except Exception as exc:
            print(f"Installer run failed: {self._log_identity()}")
            self.rollback_safely()
            self.cleanup_temp_safely()
            raise InstallError(f"Unhandled installer exception: {exc}") from exc

    def run_dry_run(self) -> None:
        """执行可验证的预检流程，不执行安装写入。"""

        print(f"Installer dry-run started: {self._log_identity()}")
        installed_version = self.recorded_installed_version()
        precheck = self.pre_check(installed_version)
        if not precheck.should_install:
            reason = precheck.reason or "already installed"
            print(f"Installer dry-run pre-check hit: {self._log_identity()}, reason={reason}")
            return
        try:
            self.prepare()
            self.download()
            self.verify_signature()
            self.pre_install()
            print(f"Installer dry-run completed: {self._log_identity()}")
        except InstallerError:
            print(f"Installer dry-run failed: {self._log_identity()}")
            self.cleanup_temp_safely()
            raise
        except Exception as exc:
            print(f"Installer dry-run failed: {self._log_identity()}")
            self.cleanup_temp_safely()
            raise InstallError(f"Unhandled installer dry-run exception: {exc}") from exc

    def recorded_installed_version(self) -> Optional[str]:
        return get_installed_version(self.resolved.config.product)

    def record_install_success(self) -> None:
        update_install_state(
            product=self.resolved.config.product,
            version=self.resolved.config.version,
            package_format=self.resolved.config.package_format,
        )

    def prepare(self) -> None:
        self.resolved.package_path.parent.mkdir(parents=True, exist_ok=True)

    def download(self) -> None:
        print(f"package_url={self.resolved.package_url}")
        print(f"signature_url={self.resolved.signature_url}")
        self.download_package()
        self.download_signature()

    def download_package(self) -> None:
        utils.ensure_local_or_download(
            self.resolved.package_url,
            self.resolved.package_path,
            self.download_defaults.timeout_seconds,
            self.download_defaults.retry,
        )

    def download_signature(self) -> None:
        utils.ensure_local_or_download(
            self.resolved.signature_url,
            self.resolved.signature_path,
            self.download_defaults.timeout_seconds,
            self.download_defaults.retry,
        )

    def verify_signature(self) -> None:
        print(f"verify_chain={self.verify_defaults.verify_chain}")
        verify_p7s_detached(
            package_path=self.resolved.package_path,
            signature_path=self.resolved.signature_path,
            root_ca=root_ca_path(),
            signature_format=self.verify_defaults.signature_format,
            verify_chain=self.verify_defaults.verify_chain,
        )

    @abstractmethod
    def pre_check(self, installed_version: Optional[str]) -> PreCheckResult:
        """安装前检查：返回安装决策。"""

    @abstractmethod
    def remove_previous_version(self, installed_version: str) -> None:
        """版本切换时删除旧版本。"""

    def pre_install(self) -> None:
        """安装前钩子，可选覆盖。"""

    @abstractmethod
    def install(self) -> None:
        """执行安装逻辑。"""

    def post_install_check(self) -> None:
        """安装后检查钩子，可选覆盖。"""

    @abstractmethod
    def rollback(self) -> None:
        """回滚逻辑，必须幂等。"""

    def cleanup_after_success(self) -> None:
        if self.download_defaults.cache_policy == CACHE_POLICY_KEEP_LATEST:
            self.keep_latest_cache()
            return
        self.cleanup_temp()

    def cleanup_temp(self) -> None:
        package_dir = self.resolved.package_path.parent
        if not package_dir.exists():
            return
        try:
            shutil.rmtree(package_dir)
        except Exception as exc:
            raise CleanupError(f"Failed to cleanup temp directory {package_dir}: {exc}") from exc

    def keep_latest_cache(self) -> None:
        package_dir = self.resolved.package_path.parent
        if not package_dir.exists():
            return
        keep_paths = {path.resolve() for path in self.cache_artifacts_to_keep() if path.exists() and path.is_file()}
        for item in package_dir.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                    continue
                if item.suffix == ".tmp":
                    item.unlink(missing_ok=True)
                    continue
                if item.resolve() in keep_paths:
                    continue
                item.unlink(missing_ok=True)
            except Exception as exc:
                raise CleanupError(f"Failed to keep latest cache under {package_dir}: {exc}") from exc

    def cache_artifacts_to_keep(self) -> Tuple[Path, ...]:
        return (self.resolved.package_path, self.resolved.signature_path)

    def rollback_safely(self) -> None:
        try:
            self.rollback()
            print(f"rollback completed for {self._log_identity()}")
        except Exception:
            print(f"rollback failed for {self._log_identity()}")

    def cleanup_temp_safely(self) -> None:
        try:
            self.cleanup_temp()
            print(f"cleanup temp completed for {self._log_identity()}")
        except Exception:
            print(f"cleanup temp failed for {self._log_identity()}")

    def _log_identity(self) -> str:
        return f"filename={self.resolved.filename}"


class TarGzInstaller(BaseInstaller):
    """tar.gz 通用安装器中间父类。"""

    def pre_check(self, installed_version: Optional[str]) -> PreCheckResult:
        install_dir = utils.resolve_install_dir(self.resolved)
        if installed_version == self.resolved.config.version and install_dir.exists():
            return PreCheckResult(should_install=False, reason=f"same version installed: {installed_version}")
        return PreCheckResult(should_install=True)

    def remove_previous_version(self, installed_version: str) -> None:
        install_dir = utils.resolve_install_dir(self.resolved)
        if install_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)

    def install(self) -> None:
        install_dir = utils.resolve_install_dir(self.resolved)
        utils.reset_install_dir(install_dir)
        utils.extract_tar_package(self.resolved.package_path, install_dir)
        utils.run_optional_install_script(install_dir)
        utils.ensure_install_dir_exists(install_dir)

    def rollback(self) -> None:
        install_dir = utils.resolve_install_dir(self.resolved)
        if install_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)

    def post_install_check(self) -> None:
        install_dir = utils.resolve_install_dir(self.resolved)
        utils.ensure_install_dir_exists(install_dir)


class RpmInstaller(BaseInstaller):
    """rpm 通用安装器中间父类。"""

    def rpm_package_name(self) -> str:
        return self.resolved.config.product

    def pre_check(self, installed_version: Optional[str]) -> PreCheckResult:
        if installed_version == self.resolved.config.version:
            return PreCheckResult(should_install=False, reason=f"same version installed: {installed_version}")
        return PreCheckResult(should_install=True)

    def remove_previous_version(self, installed_version: str) -> None:
        try:
            utils.run_rpm_command(["-e", self.rpm_package_name()])
        except InstallError:
            return

    def install(self) -> None:
        result = utils.run_rpm_command(["-Uvh", str(self.resolved.package_path)])
        if result.returncode == 0:
            return
        raise InstallError(f"rpm install failed: {result.stderr.strip()}")

    def rollback(self) -> None:
        try:
            utils.run_rpm_command(["-e", self.rpm_package_name()])
        except InstallError:
            return

    def post_install_check(self) -> None:
        result = utils.run_rpm_command(["-q", self.rpm_package_name()])
        if result.returncode == 0:
            return
        raise InstallError(f"rpm package not installed: {self.rpm_package_name()}")
