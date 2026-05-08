"""错误类型与退出码定义。"""


class InstallerError(Exception):
    """安装器基类异常。"""

    exit_code = 1


class ConfigError(InstallerError):
    """配置错误。"""

    exit_code = 10


class DownloadError(InstallerError):
    """下载错误。"""

    exit_code = 20


class SignatureVerifyError(InstallerError):
    """签名验证错误。"""

    exit_code = 40


class InstallError(InstallerError):
    """安装过程错误。"""

    exit_code = 50


class CleanupError(InstallerError):
    """清理过程错误。"""

    exit_code = 60
