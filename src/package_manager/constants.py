"""项目内共享常量定义。"""

# OS
OS_LINUX = "linux"

# Runtime arch
ARCH_ARM64 = "arm64"
ARCH_X86_64 = "x86_64"

# Machine aliases from uname/platform
MACHINE_AARCH64 = "aarch64"
MACHINE_AMD64 = "amd64"

# Package formats
PKG_FMT_RPM = "rpm"
PKG_FMT_TAR_GZ = "tar.gz"
SUPPORTED_PACKAGE_FORMATS = {PKG_FMT_RPM, PKG_FMT_TAR_GZ}

# Common file suffix
SUFFIX_RPM = ".rpm"
SUFFIX_TAR_GZ = ".tar.gz"

# Products
PRODUCT_PORTING_ADVISOR = "DevKit-Porting-Advisor"
PRODUCT_PORTING_CLI = "devkit-porting"

