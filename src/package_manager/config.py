"""YAML 配置加载模块。

职责：
1. 定位并读取 `packages.yaml`
2. 将 YAML 节点解析为运行时模型
3. 做配置完整性和版本支持约束校验
4. 以受控方式抛出 `ConfigError`，避免原始异常泄漏到调用栈
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from package_manager.errors import ConfigError
from package_manager.models import DownloadDefaults, PackageConfig, VerifyDefaults
from package_manager.paths import app_dir, project_root

PACKAGE_VERSION = "26.0.RC1"
CONFIG_FILE_ENV = "PACKAGE_MANAGER_CONFIG_FILE"
DEFAULT_CONFIG_RELATIVE = Path("config") / "packages.yaml"


@dataclass(frozen=True)
class RuntimeConfig:
    """运行时配置聚合对象。"""

    download_defaults: DownloadDefaults
    verify_defaults: VerifyDefaults
    packages: List[PackageConfig]


_RUNTIME_CONFIG_CACHE: Optional[RuntimeConfig] = None


def _load_yaml_module():
    """加载 PyYAML 模块，缺失时转换为配置错误。"""

    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise ConfigError("PyYAML is required. Install it with: python -m pip install pyyaml") from exc
    return yaml


def _config_path() -> Path:
    """解析配置文件路径，优先环境变量，其次打包态，再回退开发态。"""

    configured = os.getenv(CONFIG_FILE_ENV, "").strip()
    if configured:
        return Path(configured)
    frozen_path = app_dir() / DEFAULT_CONFIG_RELATIVE
    if frozen_path.exists():
        return frozen_path
    return project_root() / DEFAULT_CONFIG_RELATIVE


def _substitute_tokens(value: Any) -> Any:
    """递归替换配置里的占位符。"""

    if isinstance(value, str):
        return value.replace("${PACKAGE_VERSION}", PACKAGE_VERSION)
    if isinstance(value, list):
        return [_substitute_tokens(item) for item in value]
    if isinstance(value, dict):
        return {k: _substitute_tokens(v) for k, v in value.items()}
    return value


def _load_raw_config() -> Dict[str, Any]:
    """读取并解析 YAML 原始结构。"""

    path = _config_path()
    if not path.exists():
        raise ConfigError(f"Config file does not exist: {path}")
    yaml = _load_yaml_module()
    try:
        with path.open("r", encoding="utf-8") as fp:
            parsed = yaml.safe_load(fp) or {}
    except OSError as exc:
        raise ConfigError(f"Failed to read config file: {path}, error={exc}") from exc
    except Exception as exc:
        raise ConfigError(f"Failed to parse YAML config: {path}, error={exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigError(f"Config file must be a mapping: {path}")
    return _substitute_tokens(parsed)


def _required_str(node: Dict[str, Any], key: str, label: str) -> str:
    """读取必填字符串字段。"""

    value = node.get(key)
    if value is None:
        raise ConfigError(f"Missing required field '{key}' in {label}")
    text = str(value).strip()
    if not text:
        raise ConfigError(f"Field '{key}' in {label} must not be empty")
    return text


def _load_download_defaults(raw: Dict[str, Any]) -> DownloadDefaults:
    """解析下载默认配置。"""

    node = raw.get("download_defaults")
    if not isinstance(node, dict):
        raise ConfigError("download_defaults must be a mapping in YAML config")
    return DownloadDefaults(
        base_url=_required_str(node, "base_url", "download_defaults"),
        signature_suffix=str(node.get("signature_suffix", ".p7s")),
        timeout_seconds=int(node.get("timeout_seconds", 300)),
        retry=int(node.get("retry", 3)),
    )


def _load_verify_defaults(raw: Dict[str, Any]) -> VerifyDefaults:
    """解析验签默认配置。"""

    node = raw.get("verify_defaults")
    if not isinstance(node, dict):
        raise ConfigError("verify_defaults must be a mapping in YAML config")
    return VerifyDefaults(
        signature_type=str(node.get("signature_type", "p7s")),
        signature_format=str(node.get("signature_format", "DER")),
        verify_chain=bool(node.get("verify_chain", True)),
    )


def _normalize_supported_versions(value: Any) -> Tuple[str, ...]:
    """规范化支持版本列表。"""

    if value is None:
        return tuple()
    if not isinstance(value, list):
        raise ConfigError("supported_versions must be a list")
    return tuple(str(v) for v in value)


def _rpm_arch_separator(item: Dict[str, Any], label: str) -> str:
    """读取 rpm 架构分隔符，默认 '-'。"""

    raw = str(item.get("rpm_arch_separator", "-"))
    if raw in {"-", "."}:
        return raw
    raise ConfigError(f"{label}.rpm_arch_separator must be '-' or '.'")


def _load_packages(raw: Dict[str, Any]) -> List[PackageConfig]:
    """解析包配置列表。"""

    node = raw.get("packages")
    if not isinstance(node, list):
        raise ConfigError("packages must be a list in YAML config")
    packages: List[PackageConfig] = []
    for idx, item in enumerate(node):
        label = f"packages[{idx}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{label} must be a mapping")
        supported_versions = _normalize_supported_versions(item.get("supported_versions"))
        project_version = _required_str(item, "version", label)
        artifact_version = _required_str(item, "artifact_version", label)
        if supported_versions and project_version not in supported_versions:
            raise ConfigError(
                f"Configured project version '{project_version}' is not in supported_versions for product '{item.get('product')}'"
            )
        packages.append(
            PackageConfig(
                product=_required_str(item, "product", label),
                version=project_version,
                artifact_version=artifact_version,
                package_format=_required_str(item, "package_format", label),
                rpm_arch_separator=_rpm_arch_separator(item, label),
                os=str(item.get("os", "linux")),
                filename_override=str(item["filename_override"]) if item.get("filename_override") else None,
                supported_versions=supported_versions or None,
                install_dir=str(item["install_dir"]) if item.get("install_dir") else None,
                enabled=bool(item.get("enabled", True)),
            )
        )
    return packages


def _load_runtime_config() -> RuntimeConfig:
    """加载并构建运行时配置对象。"""

    raw = _load_raw_config()
    return RuntimeConfig(
        download_defaults=_load_download_defaults(raw),
        verify_defaults=_load_verify_defaults(raw),
        packages=_load_packages(raw),
    )


def get_runtime_config(reload: bool = False) -> RuntimeConfig:
    """获取运行时配置（带缓存）。"""

    global _RUNTIME_CONFIG_CACHE
    if reload or _RUNTIME_CONFIG_CACHE is None:
        _RUNTIME_CONFIG_CACHE = _load_runtime_config()
    return _RUNTIME_CONFIG_CACHE
