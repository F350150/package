import pytest

from package_manager.errors import ConfigError
from package_manager.models import PackageConfig
from package_manager.installers import get_installer_class
from package_manager.installers import TianchengTarGzInstaller


def test_registry_known():
    cfg = PackageConfig(product="tiancheng", version="1", package_format="tar.gz")
    assert get_installer_class(cfg) is TianchengTarGzInstaller


def test_registry_unknown_raises():
    cfg = PackageConfig(product="unknown", version="1", package_format="tar.gz")
    with pytest.raises(ConfigError):
        get_installer_class(cfg)
