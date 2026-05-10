"""包解析逻辑。

负责将最小配置扩展为可执行下载信息：文件名、URL、本地路径。
"""

import platform
import subprocess
from typing import Iterable, List

from package_manager.constants import (
    ARCH_ARM64,
    ARCH_X86_64,
    MACHINE_AARCH64,
    MACHINE_AMD64,
    PKG_FMT_RPM,
    PKG_FMT_TAR_GZ,
    SUFFIX_RPM,
    SUFFIX_TAR_GZ,
    SUPPORTED_PACKAGE_FORMATS,
)
from package_manager.errors import ConfigError
from package_manager.models import DownloadDefaults, PackageConfig, ResolvedPackage
from package_manager.paths import download_dir


def detect_runtime_arch() -> str:
    """识别运行时 CPU 架构并归一化为 arm64/x86_64。"""

    machine = _read_machine_name()
    if machine in {MACHINE_AARCH64, ARCH_ARM64}:
        return ARCH_ARM64
    if machine in {ARCH_X86_64, MACHINE_AMD64}:
        return ARCH_X86_64
    raise ConfigError(f"Unsupported runtime architecture: {machine}")


def _read_machine_name() -> str:
    """读取机器架构名，优先 uname -m，失败回退 platform.machine。"""

    result = subprocess.run(["uname", "-m"], capture_output=True, text=True)
    if result.returncode == 0:
        value = result.stdout.strip().lower()
        if value:
            return value
    return platform.machine().lower()


def resolve_package(package: PackageConfig, defaults: DownloadDefaults) -> ResolvedPackage:
    """解析单个包。"""

    _validate_package_format(package.package_format)
    runtime_arch = detect_runtime_arch()
    filename = build_filename(package, runtime_arch)
    return _build_resolved(package, defaults, runtime_arch, filename)


def resolve_packages(packages: Iterable[PackageConfig], defaults: DownloadDefaults) -> List[ResolvedPackage]:
    """批量解析包。"""

    return [resolve_package(pkg, defaults) for pkg in packages]


def _validate_package_format(package_format: str) -> None:
    """校验包格式是否合法。"""

    if package_format not in SUPPORTED_PACKAGE_FORMATS:
        raise ConfigError(f"Unsupported package format: {package_format}")


def build_filename(package: PackageConfig, runtime_arch: str) -> str:
    """根据规则构造包文件名。"""

    if package.filename_override:
        return package.filename_override
    token = arch_token_for_package(package.package_format, runtime_arch)
    if package.package_format == PKG_FMT_TAR_GZ:
        return f"{package.product}-{package.artifact_version}-{token}{SUFFIX_TAR_GZ}"
    return f"{package.product}-{package.artifact_version}{package.rpm_arch_separator}{token}{SUFFIX_RPM}"


def arch_token_for_package(package_format: str, runtime_arch: str) -> str:
    """根据包格式和架构返回文件名架构片段。"""

    mapping = {
        PKG_FMT_RPM: {ARCH_ARM64: MACHINE_AARCH64, ARCH_X86_64: ARCH_X86_64},
        PKG_FMT_TAR_GZ: {ARCH_ARM64: "Linux-Kunpeng", ARCH_X86_64: "Linux-x86-64"},
    }
    if package_format not in mapping:
        raise ConfigError(f"Unsupported package format: {package_format}")
    return mapping[package_format][runtime_arch]


def _build_resolved(
    package: PackageConfig,
    defaults: DownloadDefaults,
    runtime_arch: str,
    filename: str,
) -> ResolvedPackage:
    """组装 ResolvedPackage。"""

    base_url = build_project_base_url(defaults.base_url, package.version)
    package_url = f"{base_url}/{filename}"
    signature_url = f"{package_url}{defaults.signature_suffix}"
    package_dir = download_dir() / package.product
    package_path = package_dir / filename
    signature_path = package_dir / f"{filename}{defaults.signature_suffix}"
    return ResolvedPackage(
        config=package,
        runtime_arch=runtime_arch,
        filename=filename,
        package_url=package_url,
        signature_url=signature_url,
        package_path=package_path,
        signature_path=signature_path,
    )


def build_project_base_url(base_url_prefix: str, project_version: str) -> str:
    """拼接项目版本后的下载目录 URL。"""

    base = base_url_prefix.rstrip("/")
    if base.endswith(project_version):
        return base
    if base.endswith("%20") or base.endswith("/"):
        return f"{base}{project_version}"
    return f"{base}/{project_version}"
