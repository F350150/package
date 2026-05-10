"""安装器层。

分层结构：
BaseInstaller -> TarGzInstaller/RpmInstaller -> ProductInstaller
"""

import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, Type

from package_manager.constants import PKG_FMT_RPM, PKG_FMT_TAR_GZ, PRODUCT_PORTING_ADVISOR, PRODUCT_PORTING_CLI
from package_manager.downloader import download_file
from package_manager.errors import CleanupError, ConfigError, DownloadError, InstallError, InstallerError
from package_manager.install_state import get_installed_version, update_install_state
from package_manager.models import DownloadDefaults, PackageConfig, ResolvedPackage, VerifyDefaults
from package_manager.paths import app_dir, internal_dir, root_ca_path
from package_manager.resolver import build_project_base_url
from package_manager.verifier import verify_p7s_detached

InstallerKey = Tuple[str, str]


@dataclass(frozen=True)
class PreCheckResult:
    """安装前检查结果。"""

    should_install: bool
    reason: str = ""


class BaseInstaller(ABC):
    """安装流程模板父类。"""

    def __init__(self, resolved: ResolvedPackage, download_defaults: DownloadDefaults, verify_defaults: VerifyDefaults):
        """注入本次安装所需的解析结果和默认参数。"""

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

    def recorded_installed_version(self) -> Optional[str]:
        """读取记录状态中的已安装版本。"""

        return get_installed_version(self.resolved.config.product)

    def record_install_success(self) -> None:
        """记录安装成功状态。"""

        update_install_state(
            product=self.resolved.config.product,
            version=self.resolved.config.version,
            package_format=self.resolved.config.package_format,
        )

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

        ensure_local_or_download(
            self.resolved.package_url,
            self.resolved.package_path,
            self.download_defaults.timeout_seconds,
            self.download_defaults.retry,
        )

    def download_signature(self) -> None:
        """下载签名文件。"""

        ensure_local_or_download(
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
            print(f"rollback completed for {self._log_identity()}")
        except Exception:
            print(f"rollback failed for {self._log_identity()}")

    def cleanup_temp_safely(self) -> None:
        """安全清理临时文件，不让异常中断主错误链。"""

        try:
            self.cleanup_temp()
            print(f"cleanup temp completed for {self._log_identity()}")
        except Exception:
            print(f"cleanup temp failed for {self._log_identity()}")

    def _log_identity(self) -> str:
        """返回用于日志的安装目标标识。"""

        return f"filename={self.resolved.filename}"


class TarGzInstaller(BaseInstaller):
    """tar.gz 通用安装器中间父类。"""

    def pre_check(self, installed_version: Optional[str]) -> PreCheckResult:
        """同版本且目录存在时跳过安装。"""

        install_dir = resolve_install_dir(self.resolved)
        if installed_version == self.resolved.config.version and install_dir.exists():
            return PreCheckResult(should_install=False, reason=f"same version installed: {installed_version}")
        return PreCheckResult(should_install=True)

    def remove_previous_version(self, installed_version: str) -> None:
        """tar.gz 包切版本时删除旧目录。"""

        install_dir = resolve_install_dir(self.resolved)
        if install_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)

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

    def pre_check(self, installed_version: Optional[str]) -> PreCheckResult:
        """同版本 rpm 默认跳过。"""

        if installed_version == self.resolved.config.version:
            return PreCheckResult(should_install=False, reason=f"same version installed: {installed_version}")
        return PreCheckResult(should_install=True)

    def remove_previous_version(self, installed_version: str) -> None:
        """版本切换时卸载旧 rpm。"""

        try:
            run_rpm_command(["-e", self.rpm_package_name()])
        except InstallError:
            return

    def install(self) -> None:
        """执行 rpm 安装。"""

        result = run_rpm_command(["-Uvh", str(self.resolved.package_path)])
        if result.returncode == 0:
            return
        raise InstallError(f"rpm install failed: {result.stderr.strip()}")

    def rollback(self) -> None:
        """执行 rpm 卸载，失败也不抛异常（保持幂等）。"""

        try:
            run_rpm_command(["-e", self.rpm_package_name()])
        except InstallError:
            return

    def post_install_check(self) -> None:
        """验证 rpm 已安装。"""

        result = run_rpm_command(["-q", self.rpm_package_name()])
        if result.returncode == 0:
            return
        raise InstallError(f"rpm package not installed: {self.rpm_package_name()}")


class PortingAdvisorTarGzInstaller(TarGzInstaller):
    """Porting Advisor 安装器。"""

    def pre_check(self, installed_version: Optional[str]) -> PreCheckResult:
        """按目录结构判断是否已安装同版本。"""

        install_dir = resolve_install_dir(self.resolved)
        ready = has_porting_advisor_runtime_layout(install_dir)
        if installed_version == self.resolved.config.version and ready:
            return PreCheckResult(should_install=False, reason=f"same version installed: {installed_version}")
        return PreCheckResult(should_install=True)

    def install(self) -> None:
        """按手工步骤安装 Porting-Advisor，仅发布 config/jre/jar 成品。"""

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
        """校验安装后的目录结构合法。"""

        install_dir = resolve_install_dir(self.resolved)
        if has_porting_advisor_runtime_layout(install_dir):
            return
        raise InstallError(f"{PRODUCT_PORTING_ADVISOR} install validation failed under {install_dir}")


class PortingCliRpmInstaller(RpmInstaller):
    """Porting CLI rpm 安装器。"""

    def _framework_filename(self) -> str:
        """推导 devkit framework 包名。"""

        return self.resolved.filename.replace("devkit-porting-", "devkit-", 1)

    def _framework_signature_url(self) -> str:
        """返回 framework 签名下载地址。"""

        return (
            f"{self._framework_package_url()}{self.download_defaults.signature_suffix}"
        )

    def _framework_package_url(self) -> str:
        """返回 framework 包下载地址。"""

        project_base = build_project_base_url(self.download_defaults.base_url, self.resolved.config.version)
        return f"{project_base}/{self._framework_filename()}"

    def _framework_package_path(self) -> Path:
        """返回 framework 包本地路径。"""

        return self.resolved.package_path.parent / self._framework_filename()

    def _framework_signature_path(self) -> Path:
        """返回 framework 签名本地路径。"""

        return self.resolved.package_path.parent / f"{self._framework_filename()}{self.download_defaults.signature_suffix}"

    def pre_check(self, installed_version: Optional[str]) -> PreCheckResult:
        """按目录结构判断是否可跳过安装。"""

        install_dir = resolve_install_dir(self.resolved)
        ready = (install_dir / "DevKit-Porting-CLI" / "devkit").exists()
        if installed_version == self.resolved.config.version and ready:
            return PreCheckResult(should_install=False, reason=f"same version installed: {installed_version}")
        return PreCheckResult(should_install=True)

    def remove_previous_version(self, installed_version: str) -> None:
        """删除旧 rpm 与旧目录。"""

        super().remove_previous_version(installed_version)
        porting_root = resolve_install_dir(self.resolved)
        if porting_root.exists():
            shutil.rmtree(porting_root, ignore_errors=True)

    def download(self) -> None:
        """除主包外额外下载 framework 包及签名。"""

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
        """验签主包与 framework 包。"""

        super().verify_signature()
        verify_p7s_detached(
            package_path=self._framework_package_path(),
            signature_path=self._framework_signature_path(),
            root_ca=root_ca_path(),
            signature_format=self.verify_defaults.signature_format,
            verify_chain=self.verify_defaults.verify_chain,
        )

    def install(self) -> None:
        """安装双 rpm 并整理目标目录。"""

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


INSTALLER_REGISTRY: Dict[InstallerKey, Type[BaseInstaller]] = {
    (PRODUCT_PORTING_ADVISOR, PKG_FMT_TAR_GZ): PortingAdvisorTarGzInstaller,
    (PRODUCT_PORTING_CLI, PKG_FMT_RPM): PortingCliRpmInstaller,
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


def run_rpm_command(args):
    """执行 rpm 命令，不存在 rpm 时抛出明确错误。"""

    cmd = ["rpm", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise InstallError("rpm command not found in PATH on current host") from exc


def ensure_local_or_download(url: str, destination: Path, timeout_seconds: int, retry: int) -> None:
    """优先使用本地文件；缺失时下载；下载失败时给出离线投放路径。"""

    if destination.exists() and destination.is_file() and destination.stat().st_size > 0:
        print(f"Use local artifact file: {destination}")
        return
    try:
        download_file(url, destination, timeout_seconds, retry)
    except DownloadError as exc:
        target_dir = destination.parent
        raise DownloadError(
            f"{exc}. Offline install hint: place file at '{destination}' "
            f"(directory: '{target_dir}') and rerun."
        ) from exc


def has_porting_advisor_runtime_layout(path: Path) -> bool:
    """运行时成品结构：config + jre + sql-analysis jar。"""

    return (path / "config").exists() and (path / "jre").exists() and any(path.glob("sql-analysis-*.jar"))


def detect_porting_advisor_payload_dir(base_dir: Path) -> Path:
    """定位包含 Sql-Analysis/jre 压缩包的 payload 目录。"""

    if has_porting_advisor_payload_archives(base_dir):
        return base_dir
    candidates = sorted([item for item in base_dir.iterdir() if item.is_dir()], key=lambda item: item.name)
    for candidate in candidates:
        if has_porting_advisor_payload_archives(candidate):
            return candidate
    raise InstallError(f"No Porting-Advisor payload directory found under {base_dir}")


def has_porting_advisor_payload_archives(path: Path) -> bool:
    """判断目录中是否有 Porting-Advisor 关键二层包。"""

    return any(path.glob("Sql-Analysis-*-Linux-Kunpeng.tar.gz")) and any(path.glob("jre-linux-*.tar.gz"))


def install_porting_advisor_runtime_layout(payload_dir: Path, install_dir: Path) -> None:
    """按手工流程提取并发布 Porting-Advisor 运行时成品。"""

    sql_tar = first_match(payload_dir, "Sql-Analysis-*-Linux-Kunpeng.tar.gz")
    jre_tar = first_match(payload_dir, "jre-linux-*.tar.gz")
    extract_tar_package(sql_tar, payload_dir)
    extract_tar_package(jre_tar, payload_dir)

    sql_dir = first_child_dir_match(payload_dir, "Sql-Analysis-*")
    jar_file = first_match(sql_dir, "*.jar")
    if not (sql_dir / "config").exists():
        raise InstallError(f"Sql-Analysis config directory not found under {sql_dir}")
    if not (payload_dir / "jre").exists():
        raise InstallError(f"jre directory not found under {payload_dir}")

    shutil.copytree(sql_dir / "config", install_dir / "config")
    shutil.copytree(payload_dir / "jre", install_dir / "jre")
    shutil.copy2(jar_file, install_dir / jar_file.name)




def first_child_dir(path: Path, exclude: str = "") -> Path:
    """返回目录下第一个子目录。"""

    for item in path.iterdir():
        if item.is_dir() and item.name != exclude:
            return item
    raise InstallError(f"No child directory found under {path}")


def first_match(path: Path, pattern: str) -> Path:
    """返回目录下第一个匹配文件。"""

    matched = sorted(path.glob(pattern))
    if matched:
        return matched[0]
    raise InstallError(f"No file matched pattern={pattern} under {path}")


def first_child_dir_match(path: Path, pattern: str) -> Path:
    """返回目录下第一个匹配模式的子目录。"""

    matched = sorted([item for item in path.glob(pattern) if item.is_dir()])
    if matched:
        return matched[0]
    raise InstallError(f"No directory matched pattern={pattern} under {path}")

def resolve_install_dir(resolved: ResolvedPackage) -> Path:
    """解析安装目录。

    仅使用 config.install_dir：
    1. 绝对路径直接使用
    2. 相对路径基于 app_dir
    """

    configured = (resolved.config.install_dir or "").strip()
    if not configured:
        raise ConfigError(f"install_dir must be configured for product={resolved.config.product}")
    configured_path = Path(configured)
    if configured_path.is_absolute():
        return configured_path
    return app_dir() / configured_path
