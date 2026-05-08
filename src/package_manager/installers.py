"""安装器层。

分层结构：
BaseInstaller -> TarGzInstaller/RpmInstaller -> ProductInstaller
"""

import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Tuple, Type

from package_manager.downloader import download_file
from package_manager.errors import CleanupError, ConfigError, InstallError
from package_manager.models import DownloadDefaults, PackageConfig, ResolvedPackage, VerifyDefaults
from package_manager.paths import app_dir, internal_dir, root_ca_path
from package_manager.verifier import verify_p7s_detached

InstallerKey = Tuple[str, str]


class BaseInstaller(ABC):
    """安装流程模板父类。"""

    def __init__(self, resolved: ResolvedPackage, download_defaults: DownloadDefaults, verify_defaults: VerifyDefaults):
        self.resolved = resolved
        self.download_defaults = download_defaults
        self.verify_defaults = verify_defaults

    def run(self) -> None:
        """按固定模板执行安装。"""

        print(f"Installer run started: package_id={self.resolved.package_id}")
        try:
            self.prepare()
            self.download()
            self.verify_signature()
            self.pre_install()
            self.install()
            self.post_install_check()
            self.cleanup_after_success()
            print(f"Installer run completed: package_id={self.resolved.package_id}")
        except Exception:
            print(f"Installer run failed: package_id={self.resolved.package_id}")
            self.rollback_safely()
            self.cleanup_temp_safely()
            raise

    def prepare(self) -> None:
        """准备下载目录。"""

        self.resolved.package_path.parent.mkdir(parents=True, exist_ok=True)

    def download(self) -> None:
        """下载包与签名文件。"""

        print(f"package_url={self.resolved.package_url}")
        print(f"signature_url={self.resolved.signature_url}")
        self.download_package()
        self.download_signature()

    def download_package(self) -> None:
        """下载主包文件。"""

        download_file(
            self.resolved.package_url,
            self.resolved.package_path,
            self.download_defaults.timeout_seconds,
            self.download_defaults.retry,
        )

    def download_signature(self) -> None:
        """下载签名文件。"""

        download_file(
            self.resolved.signature_url,
            self.resolved.signature_path,
            self.download_defaults.timeout_seconds,
            self.download_defaults.retry,
        )

    def verify_signature(self) -> None:
        """校验 p7s 签名。"""

        print(f"verify_chain={self.verify_defaults.verify_chain}")
        verify_p7s_detached(
            package_path=self.resolved.package_path,
            signature_path=self.resolved.signature_path,
            root_ca=root_ca_path(),
            signature_format=self.verify_defaults.signature_format,
            verify_chain=self.verify_defaults.verify_chain,
        )

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
        """成功后清理下载目录。"""

        self.cleanup_temp()

    def cleanup_temp(self) -> None:
        """清理下载临时目录。"""

        package_dir = self.resolved.package_path.parent
        if not package_dir.exists():
            return
        try:
            shutil.rmtree(package_dir)
        except Exception as exc:
            raise CleanupError(f"Failed to cleanup temp directory {package_dir}: {exc}") from exc

    def rollback_safely(self) -> None:
        """安全执行回滚，不让异常中断主错误链。"""

        try:
            self.rollback()
            print(f"rollback completed for package_id={self.resolved.package_id}")
        except Exception:
            print(f"rollback failed for package_id={self.resolved.package_id}")

    def cleanup_temp_safely(self) -> None:
        """安全清理临时文件，不让异常中断主错误链。"""

        try:
            self.cleanup_temp()
            print(f"cleanup temp completed for package_id={self.resolved.package_id}")
        except Exception:
            print(f"cleanup temp failed for package_id={self.resolved.package_id}")


class TarGzInstaller(BaseInstaller):
    """tar.gz 通用安装器中间父类。"""

    def install(self) -> None:
        """解压并执行 install.sh（如果存在）。"""

        install_dir = resolve_install_dir(self.resolved)
        reset_install_dir(install_dir)
        extract_tar_package(self.resolved.package_path, install_dir)
        run_optional_install_script(install_dir)
        ensure_install_dir_exists(install_dir)

    def rollback(self) -> None:
        """删除安装目录，保证幂等。"""

        install_dir = resolve_install_dir(self.resolved)
        if install_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)

    def post_install_check(self) -> None:
        """检查安装目录存在。"""

        install_dir = resolve_install_dir(self.resolved)
        ensure_install_dir_exists(install_dir)


class RpmInstaller(BaseInstaller):
    """rpm 通用安装器中间父类。"""

    def rpm_package_name(self) -> str:
        """返回 rpm 包名，可由子类覆盖。"""

        return self.resolved.config.product

    def install(self) -> None:
        """执行 rpm 安装。"""

        result = subprocess.run(["rpm", "-Uvh", str(self.resolved.package_path)], capture_output=True, text=True)
        if result.returncode == 0:
            return
        raise InstallError(f"rpm install failed: {result.stderr.strip()}")

    def rollback(self) -> None:
        """执行 rpm 卸载，失败也不抛异常（保持幂等）。"""

        subprocess.run(["rpm", "-e", self.rpm_package_name()], capture_output=True, text=True)

    def post_install_check(self) -> None:
        """验证 rpm 已安装。"""

        result = subprocess.run(["rpm", "-q", self.rpm_package_name()], capture_output=True, text=True)
        if result.returncode == 0:
            return
        raise InstallError(f"rpm package not installed: {self.rpm_package_name()}")


class TianchengTarGzInstaller(TarGzInstaller):
    """天成 tar.gz 安装器（当前沿用通用逻辑）。"""


class TianchengRpmInstaller(RpmInstaller):
    """天成 rpm 安装器（当前沿用通用逻辑）。"""


INSTALLER_REGISTRY: Dict[InstallerKey, Type[BaseInstaller]] = {
    ("tiancheng", "tar.gz"): TianchengTarGzInstaller,
    ("tiancheng", "rpm"): TianchengRpmInstaller,
}


def get_installer_class(config: PackageConfig) -> Type[BaseInstaller]:
    """根据产品和包格式返回安装器类。"""

    key = (config.product, config.package_format)
    try:
        return INSTALLER_REGISTRY[key]
    except KeyError as exc:
        raise ConfigError(f"Unknown installer mapping for product={config.product}, format={config.package_format}") from exc


def reset_install_dir(install_dir):
    """重置安装目录。"""

    if install_dir.exists():
        shutil.rmtree(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)


def extract_tar_package(package_path, install_dir):
    """解压 tar.gz 包。"""

    extract = subprocess.run(["tar", "-xzf", str(package_path), "-C", str(install_dir)], capture_output=True, text=True)
    if extract.returncode == 0:
        return
    raise InstallError(f"tar extract failed: {extract.stderr.strip()}")


def run_optional_install_script(install_dir):
    """如果存在 install.sh 则执行。"""

    install_script = install_dir / "install.sh"
    if not install_script.exists():
        return
    result = subprocess.run(["bash", str(install_script)], cwd=str(install_dir), capture_output=True, text=True)
    if result.returncode == 0:
        return
    raise InstallError(f"install.sh failed: {result.stderr.strip()}")


def ensure_install_dir_exists(install_dir):
    """校验安装目录存在。"""

    if install_dir.exists():
        return
    raise InstallError(f"Install directory missing after installation: {install_dir}")


def resolve_install_dir(resolved: ResolvedPackage) -> Path:
    """解析安装目录。

    优先级：
    1. config.install_dir（绝对路径直接使用；相对路径基于 app_dir）
    2. 默认 internal_dir/products/<product>
    """

    configured = resolved.config.install_dir
    if configured:
        configured_path = Path(configured)
        if configured_path.is_absolute():
            return configured_path
        return app_dir() / configured_path
    return internal_dir() / "products" / resolved.config.product
