"""安装状态存储（隐藏 YAML 文件）。"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from package_manager.errors import ConfigError
from package_manager.paths import install_state_path

INSTALL_STATE_FILE_ENV = "PACKAGE_MANAGER_INSTALL_STATE_FILE"


def _load_yaml_module():
    """加载 PyYAML 模块。"""

    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise ConfigError("PyYAML is required. Install it with: python -m pip install pyyaml") from exc
    return yaml


def _initial_state() -> Dict[str, Any]:
    """返回空状态结构。"""

    return {"products": {}}


def load_install_state(path: Optional[Path] = None) -> Dict[str, Any]:
    """读取安装状态，异常转换为配置错误。"""

    target = path or _resolve_state_path()
    if not target.exists():
        return _initial_state()
    yaml = _load_yaml_module()
    try:
        with target.open("r", encoding="utf-8") as fp:
            parsed = yaml.safe_load(fp) or {}
    except OSError as exc:
        raise ConfigError(f"Failed to read install state file: {target}, error={exc}") from exc
    except Exception as exc:
        raise ConfigError(f"Failed to parse install state YAML: {target}, error={exc}") from exc
    if not isinstance(parsed, dict):
        return _initial_state()
    products = parsed.get("products")
    if not isinstance(products, dict):
        return _initial_state()
    return parsed


def get_installed_version(product: str, path: Optional[Path] = None) -> Optional[str]:
    """获取某个产品记录的已安装版本。"""

    state = load_install_state(path)
    node = state.get("products", {}).get(product)
    if not isinstance(node, dict):
        return None
    value = node.get("installed_version")
    return str(value) if value else None


def update_install_state(
    product: str,
    version: str,
    package_format: str,
    path: Optional[Path] = None,
) -> None:
    """更新某个产品的安装状态（仅安装成功后调用）。"""

    target = path or _resolve_state_path()
    state = load_install_state(target)
    products = state.setdefault("products", {})
    products[product] = {
        "installed_version": version,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "package_format": package_format,
        "last_result": "success",
    }
    _atomic_write_yaml(target, state)


def _atomic_write_yaml(path: Path, data: Dict[str, Any]) -> None:
    """原子写入 YAML，避免中断导致状态文件损坏。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    yaml = _load_yaml_module()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fp:
        yaml.safe_dump(data, fp, sort_keys=False, allow_unicode=False)
    tmp_path.replace(path)


def _resolve_state_path() -> Path:
    """解析状态文件路径，优先环境变量。"""

    configured = os.getenv(INSTALL_STATE_FILE_ENV, "").strip()
    if configured:
        return Path(configured)
    return install_state_path()
