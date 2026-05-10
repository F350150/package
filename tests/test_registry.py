import pytest

from package_manager.errors import ConfigError
from package_manager.models import PackageConfig
from package_manager.installers import get_installer_class
from package_manager.installers import PortingAdvisorTarGzInstaller


def test_registry_known():
    cfg = PackageConfig(
        product="DevKit-Porting-Advisor",
        version="1",
        artifact_version="1",
        package_format="tar.gz",
        install_dir="_internal/porting_cli",
    )
    assert get_installer_class(cfg) is PortingAdvisorTarGzInstaller


def test_registry_unknown_raises():
    cfg = PackageConfig(
        product="unknown",
        version="1",
        artifact_version="1",
        package_format="tar.gz",
        install_dir="_internal/products/unknown",
    )
    with pytest.raises(ConfigError):
        get_installer_class(cfg)
