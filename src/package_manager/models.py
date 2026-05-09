"""数据模型定义。

该文件只存放纯数据结构，避免掺杂业务逻辑，方便测试与演进。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class DownloadDefaults:
    """下载默认参数。"""

    base_url: str
    signature_suffix: str = ".p7s"
    timeout_seconds: int = 300
    retry: int = 3


@dataclass(frozen=True)
class VerifyDefaults:
    """验签默认参数。"""

    signature_type: str = "p7s"
    signature_format: str = "DER"
    verify_chain: bool = True


@dataclass(frozen=True)
class PackageConfig:
    """包配置。

    字段语义：
    1. version：项目版本（用于拼接下载目录与安装状态管理）
    2. artifact_version：产品包自身版本（用于拼接文件名）
    """

    product: str
    version: str
    artifact_version: str
    package_format: str  # 仅支持: "rpm" | "tar.gz"
    rpm_arch_separator: str = "-"
    os: str = "linux"
    filename_override: Optional[str] = None
    supported_versions: Optional[Tuple[str, ...]] = None
    # 安装目录：支持绝对路径或相对 app_dir 的相对路径。
    # 为空时走默认路径（_internal/products/<product>）。
    install_dir: Optional[str] = None
    enabled: bool = True


@dataclass(frozen=True)
class ResolvedPackage:
    """解析后的可执行下载与安装信息。"""

    config: PackageConfig
    package_id: str
    runtime_arch: str
    filename: str
    package_url: str
    signature_url: str
    package_path: Path
    signature_path: Path
