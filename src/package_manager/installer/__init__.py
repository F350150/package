"""安装器包。

职责：
1. 提供安装模板基类与产品安装器
2. 通过模块自动发现构建安装器注册表
"""

from .base import BaseInstaller, PreCheckResult, RpmInstaller, TarGzInstaller
from .registry import (
    INSTALLER_PLUGINS_ENV,
    discover_installer_plugins,
    get_installer_class,
    installer_registry,
)
from .utils import (
    detect_porting_advisor_payload_dir,
    ensure_local_or_download,
    extract_tar_package,
    first_child_dir,
    first_child_dir_match,
    first_match,
    has_porting_advisor_payload_archives,
    has_porting_advisor_runtime_layout,
    install_porting_advisor_runtime_layout,
    reset_install_dir,
    resolve_install_dir,
    run_optional_install_script,
    run_rpm_command,
)
from .porting_advisor import PortingAdvisorTarGzInstaller
from .porting_cli import PortingCliRpmInstaller

__all__ = [
    "BaseInstaller",
    "PreCheckResult",
    "RpmInstaller",
    "TarGzInstaller",
    "PortingAdvisorTarGzInstaller",
    "PortingCliRpmInstaller",
    "INSTALLER_PLUGINS_ENV",
    "discover_installer_plugins",
    "get_installer_class",
    "installer_registry",
    "detect_porting_advisor_payload_dir",
    "ensure_local_or_download",
    "extract_tar_package",
    "first_child_dir",
    "first_child_dir_match",
    "first_match",
    "has_porting_advisor_payload_archives",
    "has_porting_advisor_runtime_layout",
    "install_porting_advisor_runtime_layout",
    "reset_install_dir",
    "resolve_install_dir",
    "run_optional_install_script",
    "run_rpm_command",
]
