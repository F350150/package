"""安装器注册表与自动发现。"""

import importlib
import os
import pkgutil
from typing import Dict, Iterable, Optional, Tuple, Type

from package_manager.errors import ConfigError
from package_manager.models import PackageConfig

from .base import BaseInstaller

InstallerKey = Tuple[str, str]
INSTALLER_PLUGINS_ENV = "PACKAGE_MANAGER_INSTALLER_PLUGINS"
_INTERNAL_MODULE_IGNORE = {"package_manager.installer.base", "package_manager.installer.registry", "package_manager.installer.utils"}

_INSTALLER_REGISTRY_CACHE: Optional[Dict[InstallerKey, Type[BaseInstaller]]] = None


def get_installer_class(config: PackageConfig) -> Type[BaseInstaller]:
    """根据产品和包格式返回安装器类。"""

    registry = installer_registry()
    key = (config.product, config.package_format)
    try:
        return registry[key]
    except KeyError as exc:
        raise ConfigError(f"Unknown installer mapping for product={config.product}, format={config.package_format}") from exc


def installer_registry(reload: bool = False) -> Dict[InstallerKey, Type[BaseInstaller]]:
    """返回安装器注册表（内部模块 + 外部插件自动发现）。"""

    global _INSTALLER_REGISTRY_CACHE
    if reload or _INSTALLER_REGISTRY_CACHE is None:
        _INSTALLER_REGISTRY_CACHE = discover_installer_plugins()
    return _INSTALLER_REGISTRY_CACHE


def discover_installer_plugins() -> Dict[InstallerKey, Type[BaseInstaller]]:
    """自动发现并加载安装器插件注册表。"""

    discovered: Dict[InstallerKey, Type[BaseInstaller]] = {}
    for module_name in iter_plugin_module_names():
        module = importlib.import_module(module_name)
        register = getattr(module, "REGISTER", None)
        if register is None:
            continue
        if not isinstance(register, dict):
            raise ConfigError(f"Installer plugin REGISTER must be dict: module={module_name}")
        for key, installer_cls in register.items():
            normalized_key = validate_installer_key(key, module_name)
            validate_installer_class(installer_cls, module_name)
            if normalized_key in discovered:
                raise ConfigError(f"Duplicate installer mapping found in module={module_name} key={normalized_key}")
            discovered[normalized_key] = installer_cls
    return discovered


def iter_plugin_module_names() -> Iterable[str]:
    """返回需要自动加载的插件模块名。"""

    yielded = set()

    import package_manager.installer as installer_pkg

    for entry in pkgutil.iter_modules(installer_pkg.__path__, installer_pkg.__name__ + "."):
        if entry.ispkg:
            continue
        if entry.name in _INTERNAL_MODULE_IGNORE:
            continue
        yielded.add(entry.name)
        yield entry.name

    try:
        import package_manager.installer_plugins as plugin_pkg

        for entry in pkgutil.iter_modules(plugin_pkg.__path__, plugin_pkg.__name__ + "."):
            if entry.ispkg:
                continue
            if entry.name in yielded:
                continue
            yielded.add(entry.name)
            yield entry.name
    except ModuleNotFoundError:
        pass

    env_value = os.getenv(INSTALLER_PLUGINS_ENV, "").strip()
    if not env_value:
        return
    for module_name in [item.strip() for item in env_value.split(",") if item.strip()]:
        if module_name in yielded:
            continue
        yielded.add(module_name)
        yield module_name


def validate_installer_key(key, module_name: str) -> InstallerKey:
    """校验插件中的安装器映射键。"""

    if not isinstance(key, tuple) or len(key) != 2:
        raise ConfigError(f"Invalid installer key in module={module_name}: {key}")
    product, package_format = key
    if not isinstance(product, str) or not isinstance(package_format, str):
        raise ConfigError(f"Installer key must be tuple[str, str] in module={module_name}: {key}")
    return product, package_format


def validate_installer_class(installer_cls, module_name: str) -> None:
    """校验插件中的安装器类。"""

    if not isinstance(installer_cls, type):
        raise ConfigError(f"Installer mapping value must be a class in module={module_name}: {installer_cls}")
    if not issubclass(installer_cls, BaseInstaller):
        raise ConfigError(f"Installer class must inherit BaseInstaller in module={module_name}: {installer_cls}")
