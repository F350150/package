"""数据模型定义。

该文件只存放纯数据结构，避免掺杂业务逻辑，方便测试与演进。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


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

    只保留最小必要字段：产品名、版本、包格式。
    其余冗余信息由 resolver 在运行时推导。
    """

    product: str
    version: str
    package_format: str  # 仅支持: "rpm" | "tar.gz"
    os: str = "linux"
    filename_override: Optional[str] = None
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
