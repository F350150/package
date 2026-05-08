"""内置配置模块。"""

from package_manager.models import DownloadDefaults, PackageConfig, VerifyDefaults

PACKAGE_VERSION = "26.0.RC1"

DOWNLOAD_DEFAULTS = DownloadDefaults(
    # 真实下载源（已按你的链接配置）
    base_url="https://kunpeng-repo.obs.cn-north-4.myhuaweicloud.com/Kunpeng%20DevKit/Kunpeng%20DevKit%2026.0.RC1",
    signature_suffix=".p7s",
    timeout_seconds=300,
    retry=3,
)

VERIFY_DEFAULTS = VerifyDefaults(
    signature_type="p7s",
    signature_format="DER",
    verify_chain=True,
)

PACKAGES = [
    PackageConfig(
        product="tiancheng",
        version=PACKAGE_VERSION,
        package_format="tar.gz",
        install_dir="_internal/products/tiancheng",
        enabled=True,
    )
]
