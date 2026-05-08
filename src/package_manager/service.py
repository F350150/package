"""安装服务层。

提供给 main 的一行调用入口：run_with_builtin_config。
"""

from typing import Iterable, List, Optional

from package_manager.config import DOWNLOAD_DEFAULTS, PACKAGES, VERIFY_DEFAULTS
from package_manager.errors import ConfigError
from package_manager.installers import get_installer_class
from package_manager.models import PackageConfig
from package_manager.resolver import resolve_package, resolve_packages


def run_with_builtin_config(name: Optional[str] = None, package_id: Optional[str] = None, list_packages: bool = False) -> int:
    """按内置配置执行：列包、按 name 安装、按 id 安装或全量安装。"""

    if list_packages:
        return list_enabled_packages()
    ensure_name_and_id_not_conflict(name, package_id)
    selected = select_packages(name, package_id)
    return run_packages(selected)


def list_enabled_packages(packages: Iterable[PackageConfig] = PACKAGES) -> int:
    """列出可安装包（运行时解析后视图）。"""

    for resolved in resolve_packages(enabled_packages(packages), DOWNLOAD_DEFAULTS):
        print(format_package_line(resolved))
    return 0


def enabled_packages(packages: Iterable[PackageConfig] = PACKAGES) -> List[PackageConfig]:
    """过滤启用状态的包。"""

    return [pkg for pkg in packages if pkg.enabled]


def ensure_name_and_id_not_conflict(name: Optional[str], package_id: Optional[str]) -> None:
    """防止 name 与 package_id 同时传入。"""

    if name and package_id:
        raise ConfigError("Use either name or package-id, not both")


def select_packages(name: Optional[str], package_id: Optional[str]) -> List[PackageConfig]:
    """根据 CLI 条件选择目标包。"""

    if name:
        return get_packages_by_name(name)
    if package_id:
        return [get_package_by_id(package_id)]
    return enabled_packages()


def get_packages_by_name(name: str, packages: Iterable[PackageConfig] = PACKAGES) -> List[PackageConfig]:
    """按产品名选择包（忽略大小写）。"""

    target_name = normalize_required_value(name, "Package name")
    matches = [pkg for pkg in enabled_packages(packages) if pkg.product.lower() == target_name.lower()]
    if matches:
        return matches
    raise ConfigError(f"No enabled package found for name: {name}")


def get_package_by_id(package_id: str, packages: Iterable[PackageConfig] = PACKAGES) -> PackageConfig:
    """按解析后的 package_id 选择包。"""

    target_id = normalize_required_value(package_id, "Package id")
    for pkg in enabled_packages(packages):
        if resolve_package(pkg, DOWNLOAD_DEFAULTS).package_id == target_id:
            return pkg
    raise ConfigError(f"No enabled package found for id: {package_id}")


def normalize_required_value(value: str, label: str) -> str:
    """对必填字符串做清洗和非空校验。"""

    target = (value or "").strip()
    if target:
        return target
    raise ConfigError(f"{label} must not be empty")


def run_packages(packages: Iterable[PackageConfig]) -> int:
    """执行安装。"""

    for pkg in packages:
        resolved = resolve_package(pkg, DOWNLOAD_DEFAULTS)
        installer_cls = get_installer_class(pkg)
        installer = installer_cls(resolved, DOWNLOAD_DEFAULTS, VERIFY_DEFAULTS)
        installer.run()
    return 0


def format_package_line(resolved) -> str:
    """格式化 `--list-packages` 输出。"""

    install_dir = resolved.config.install_dir or "_internal/products/<product>"
    return (
        f"{resolved.package_id}\t{resolved.config.product}\t{resolved.config.version}\t"
        f"{resolved.config.os}\t{resolved.runtime_arch}\tformat={resolved.config.package_format}\t"
        f"filename={resolved.filename}\tinstall_dir={install_dir}\t"
        f"enabled={str(resolved.config.enabled).lower()}"
    )
