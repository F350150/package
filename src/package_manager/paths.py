"""路径与运行环境处理。

统一管理开发态与打包态（PyInstaller）路径，避免业务代码散落路径判断。
"""

import os
import sys
from pathlib import Path

from package_manager.errors import ConfigError

CERT_FILENAME = "huawei_integrity_root_ca_g2.pem"
OPENSSL_BIN_NAME = "openssl"
INTERNAL_DIR_NAME = "_internal"
STATE_DIR_NAME = ".package-manager"
STATE_FILE_NAME = ".install_state.yaml"
DEFAULT_CONFIG_RELATIVE = Path("config") / "packages.yaml"
CONFIG_FILE_ENV = "PACKAGE_MANAGER_CONFIG_FILE"


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
    """返回内部根证书路径，缺失则抛错。"""

    internal_pem = internal_dir() / "openssl" / "pems" / CERT_FILENAME
    if not internal_pem.exists():
        raise ConfigError(f"Internal root CA file does not exist: {internal_pem}")
    return internal_pem


def openssl_bin_path() -> Path:
    """返回内置 openssl 路径。"""

    return internal_dir() / "openssl" / "bin" / OPENSSL_BIN_NAME


def openssl_lib_dir() -> Path:
    """返回内置 openssl 动态库目录。"""

    return internal_dir() / "openssl" / "lib"


def download_dir() -> Path:
    """返回下载缓存目录。"""

    return internal_dir() / "packages"


def log_dir() -> Path:
    """返回日志目录。"""

    return internal_dir() / "logs"


def state_dir() -> Path:
    """返回运行时状态目录（隐藏目录）。"""

    return app_dir() / STATE_DIR_NAME


def install_state_path() -> Path:
    """返回安装状态文件路径（隐藏文件）。"""

    return state_dir() / STATE_FILE_NAME


def runtime_config_path() -> Path:
    """返回运行时配置文件路径。

    解析顺序：
    1. 环境变量 `PACKAGE_MANAGER_CONFIG_FILE`
    2. 打包产物目录 `app_dir()/config/packages.yaml`
    3. 源码目录 `project_root()/config/packages.yaml`
    """

    env_value = os.getenv(CONFIG_FILE_ENV, "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    frozen_path = app_dir() / DEFAULT_CONFIG_RELATIVE
    if frozen_path.exists():
        return frozen_path
    return project_root() / DEFAULT_CONFIG_RELATIVE
