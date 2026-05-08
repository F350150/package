"""路径与运行环境处理。

统一管理开发态与打包态（PyInstaller）路径，避免业务代码散落路径判断。
"""

import sys
from pathlib import Path

CERT_FILENAME = "huawei_integrity_root_ca_g2.pem"
OPENSSL_BIN_NAME = "openssl"
INTERNAL_DIR_NAME = "_internal"


def is_frozen() -> bool:
    """判断是否运行在打包态。"""

    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """返回项目根目录（开发态）。"""

    return Path(__file__).resolve().parents[2]


def app_dir() -> Path:
    """返回可执行文件所在目录或项目根目录。"""

    if is_frozen():
        return Path(sys.executable).resolve().parent
    return project_root()


def resource_dir() -> Path:
    """返回资源目录（onefile 时为 _MEIPASS）。"""

    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return app_dir()


def internal_dir() -> Path:
    """返回内部运行依赖目录。"""

    return app_dir() / INTERNAL_DIR_NAME


def root_ca_path() -> Path:
    """返回根证书路径，优先内部目录。"""

    internal_pem = internal_dir() / "openssl" / "pems" / CERT_FILENAME
    if internal_pem.exists():
        return internal_pem
    return resource_dir() / "certs" / CERT_FILENAME


def openssl_bin_path() -> Path:
    """返回内置 openssl 路径。"""

    return internal_dir() / "openssl" / "bin" / OPENSSL_BIN_NAME


def download_dir() -> Path:
    """返回下载缓存目录。"""

    return internal_dir() / "packages"


def log_dir() -> Path:
    """返回日志目录。"""

    return internal_dir() / "logs"
