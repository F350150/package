"""安装服务编排层。

职责：
1. 读取运行时配置
2. 根据 CLI 条件选择包
3. 驱动安装器执行
"""

from typing import Iterable, List, Optional

from package_manager.config import RuntimeConfig, get_runtime_config
from package_manager.errors import ConfigError
from package_manager.installer import get_installer_class
from package_manager.models import PackageConfig
from package_manager.resolver import resolve_package


def run_with_builtin_config(name: Optional[str] = None, dry_run: bool = False) -> int:
    """按 YAML 配置执行，仅支持按 name 安装。"""

    runtime = get_runtime_config()
    selected = select_packages(name, runtime)
    return run_packages(selected, runtime, dry_run=dry_run)


def enabled_packages(packages: Iterable[PackageConfig]) -> List[PackageConfig]:
    """过滤启用状态的包。"""

    return [pkg for pkg in packages if pkg.enabled]


def select_packages(name: Optional[str], runtime: RuntimeConfig) -> List[PackageConfig]:
    """根据 CLI 条件选择目标包（仅支持 name）。"""

    if not name:
        raise ConfigError("`--name` is required")
    return get_packages_by_name(name, runtime.packages)


def get_packages_by_name(name: str, packages: Iterable[PackageConfig]) -> List[PackageConfig]:
    """按产品名选择包（忽略大小写）。"""

    target_name = normalize_required_value(name, "Package name")
    matches = [pkg for pkg in enabled_packages(packages) if pkg.product.lower() == target_name.lower()]
    if matches:
        return matches
    raise ConfigError(f"No enabled package found for name: {name}")


def normalize_required_value(value: str, label: str) -> str:
    """对必填字符串做清洗和非空校验。"""

    target = (value or "").strip()
    if target:
        return target
    raise ConfigError(f"{label} must not be empty")


def run_packages(packages: Iterable[PackageConfig], runtime: RuntimeConfig, dry_run: bool = False) -> int:
    """执行安装或预检。"""

    for pkg in packages:
        resolved = resolve_package(pkg, runtime.download_defaults)
        installer_cls = get_installer_class(pkg)
        installer = installer_cls(resolved, runtime.download_defaults, runtime.verify_defaults)
        if dry_run:
            installer.run_dry_run()
            continue
        installer.run()
    return 0
