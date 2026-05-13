import pytest
import sys

from package_manager.errors import ConfigError
from package_manager.models import PackageConfig
from package_manager.installer import get_installer_class, installer_registry
from package_manager.installer import PortingAdvisorTarGzInstaller


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


def test_registry_discovers_external_plugin(monkeypatch, tmp_path):
    plugin_file = tmp_path / "my_installer_plugin.py"
    plugin_file.write_text(
        """
from package_manager.installer import PortingAdvisorTarGzInstaller

REGISTER = {
    ("demo-plugin-product", "tar.gz"): PortingAdvisorTarGzInstaller,
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PACKAGE_MANAGER_INSTALLER_PLUGINS", "my_installer_plugin")
    monkeypatch.syspath_prepend(str(tmp_path))

    registry = installer_registry(reload=True)
    assert ("demo-plugin-product", "tar.gz") in registry

    # 清理导入缓存，避免影响其他用例。
    sys.modules.pop("my_installer_plugin", None)
