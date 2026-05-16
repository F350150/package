"""YAML 配置加载模块。

职责：
1. 定位并读取 `packages.yaml`
2. 将 YAML 节点解析为运行时模型
3. 做配置完整性和版本支持约束校验
4. 以受控方式抛出 `ConfigError`，避免原始异常泄漏到调用栈
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from package_manager.constants import (
    CACHE_POLICY_CLEANUP,
    OS_LINUX,
    PKG_FMT_RPM,
    PKG_FMT_TAR_GZ,
    SUPPORTED_CACHE_POLICIES,
)
from package_manager.errors import ConfigError
from package_manager.models import DownloadDefaults, PackageConfig, VerifyDefaults
from package_manager.paths import runtime_config_path


@dataclass(frozen=True)
class RuntimeConfig:
    """运行时配置聚合对象。"""

    download_defaults: DownloadDefaults
    verify_defaults: VerifyDefaults
    packages: List[PackageConfig]


class DownloadDefaultsNode(BaseModel):
    """下载默认配置节点。"""

    model_config = ConfigDict(extra="ignore")

    base_url: str
    signature_suffix: str = ".p7s"
    timeout_seconds: int = 300
    retry: int = 3
    cache_policy: str = CACHE_POLICY_CLEANUP

    @field_validator("base_url", "signature_suffix", mode="before")
    @classmethod
    def _non_empty_text(cls, value: Any) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("cache_policy")
    @classmethod
    def _valid_cache_policy(cls, value: str) -> str:
        if value not in SUPPORTED_CACHE_POLICIES:
            raise ValueError(f"must be one of {sorted(SUPPORTED_CACHE_POLICIES)}")
        return value


class VerifyDefaultsNode(BaseModel):
    """验签默认配置节点。"""

    model_config = ConfigDict(extra="ignore")

    signature_type: str = "p7s"
    signature_format: str = "DER"
    verify_chain: bool = True

    @field_validator("signature_type", "signature_format", mode="before")
    @classmethod
    def _non_empty_text(cls, value: Any) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class PackageNode(BaseModel):
    """包配置节点。"""

    model_config = ConfigDict(extra="ignore")

    product: str
    project_version: str = Field(validation_alias=AliasChoices("project_version", "version"))
    artifact_version: str
    package_format: str
    rpm_arch_separator: str = "-"
    os: str = OS_LINUX
    install_dir: str
    filename_override: Optional[str] = None
    supported_versions: Optional[List[str]] = None
    enabled: bool = True

    @field_validator("product", "project_version", "artifact_version", "package_format", "os", "install_dir", mode="before")
    @classmethod
    def _required_text(cls, value: Any) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("filename_override", mode="before")
    @classmethod
    def _optional_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("supported_versions", mode="before")
    @classmethod
    def _supported_versions_to_list(cls, value: Any) -> Optional[List[str]]:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("must be a list")
        return [str(v).strip() for v in value if str(v).strip()]

    @field_validator("rpm_arch_separator")
    @classmethod
    def _valid_rpm_arch_separator(cls, value: str) -> str:
        if value not in {"-", "."}:
            raise ValueError("must be '-' or '.'")
        return value

    @field_validator("package_format")
    @classmethod
    def _valid_package_format(cls, value: str) -> str:
        if value not in {PKG_FMT_RPM, PKG_FMT_TAR_GZ}:
            raise ValueError(f"must be '{PKG_FMT_RPM}' or '{PKG_FMT_TAR_GZ}'")
        return value

    @model_validator(mode="after")
    def _validate_supported_versions(self) -> "PackageNode":
        supported = self.supported_versions or []
        if supported and self.project_version not in supported:
            raise ValueError(
                f"Configured project version '{self.project_version}' is not in supported_versions for product '{self.product}'"
            )
        return self


class ConfigNode(BaseModel):
    """根配置节点。"""

    model_config = ConfigDict(extra="ignore")

    download_defaults: DownloadDefaultsNode
    verify_defaults: VerifyDefaultsNode
    packages: List[PackageNode]

    @model_validator(mode="before")
    @classmethod
    def _forbid_field_aliases(cls, data: Any) -> Any:
        if isinstance(data, Mapping) and "field_aliases" in data:
            raise ValueError("field_aliases is no longer supported; please use canonical YAML keys")
        return data


_RUNTIME_CONFIG_CACHE: Optional[RuntimeConfig] = None


def _format_validation_error(exc: ValidationError) -> str:
    """格式化 Pydantic 校验错误。"""

    parts: List[str] = []
    for err in exc.errors(include_url=False):
        loc = ".".join(str(token) for token in err.get("loc", ()))
        msg = str(err.get("msg", "validation error"))
        if loc:
            parts.append(f"{loc}: {msg}")
        else:
            parts.append(msg)
    return "; ".join(parts)


def _load_raw_config() -> Dict[str, Any]:
    """读取并解析 YAML 原始结构。"""

    path = runtime_config_path()
    return load_raw_config_from_path(path)


def load_raw_config_from_path(path: Path) -> Dict[str, Any]:
    """从指定路径读取并解析 YAML 原始结构。"""

    if not path.exists():
        raise ConfigError(f"Config file does not exist: {path}")
    try:
        with path.open("r", encoding="utf-8") as fp:
            parsed = yaml.safe_load(fp) or {}
    except OSError as exc:
        raise ConfigError(f"Failed to read config file: {path}, error={exc}") from exc
    except Exception as exc:
        raise ConfigError(f"Failed to parse YAML config: {path}, error={exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigError(f"Config file must be a mapping: {path}")
    return parsed


def _load_runtime_config() -> RuntimeConfig:
    """加载并构建运行时配置对象。"""

    raw = _load_raw_config()
    return runtime_config_from_raw(raw)


def runtime_config_from_raw(raw: Dict[str, Any]) -> RuntimeConfig:
    """从 YAML 字典构建运行时配置对象。"""

    try:
        node = ConfigNode.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc

    return RuntimeConfig(
        download_defaults=DownloadDefaults(
            base_url=node.download_defaults.base_url,
            signature_suffix=node.download_defaults.signature_suffix,
            timeout_seconds=node.download_defaults.timeout_seconds,
            retry=node.download_defaults.retry,
            cache_policy=node.download_defaults.cache_policy,
        ),
        verify_defaults=VerifyDefaults(
            signature_type=node.verify_defaults.signature_type,
            signature_format=node.verify_defaults.signature_format,
            verify_chain=node.verify_defaults.verify_chain,
        ),
        packages=[
            PackageConfig(
                product=item.product,
                version=item.project_version,
                artifact_version=item.artifact_version,
                package_format=item.package_format,
                rpm_arch_separator=item.rpm_arch_separator,
                os=item.os,
                install_dir=item.install_dir,
                filename_override=item.filename_override,
                supported_versions=tuple(item.supported_versions) if item.supported_versions else None,
                enabled=item.enabled,
            )
            for item in node.packages
        ],
    )


def load_runtime_config_from_path(path: Path) -> RuntimeConfig:
    """从指定配置路径加载运行时配置（不使用全局缓存）。"""

    raw = load_raw_config_from_path(path)
    return runtime_config_from_raw(raw)


def get_runtime_config(reload: bool = False) -> RuntimeConfig:
    """获取运行时配置（带缓存）。"""

    global _RUNTIME_CONFIG_CACHE
    if reload or _RUNTIME_CONFIG_CACHE is None:
        _RUNTIME_CONFIG_CACHE = _load_runtime_config()
    return _RUNTIME_CONFIG_CACHE
