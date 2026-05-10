import pytest

from package_manager.config import RuntimeConfig
from package_manager.errors import ConfigError
from package_manager.models import DownloadDefaults, PackageConfig, VerifyDefaults
from package_manager.service import get_packages_by_name, run_with_builtin_config, select_packages


def _packages():
    return [
        PackageConfig(
            product="DevKit-Porting-Advisor",
            version="1",
            artifact_version="1",
            package_format="tar.gz",
            install_dir="_internal/porting_cli",
            enabled=True,
        ),
        PackageConfig(
            product="devkit-porting",
            version="1",
            artifact_version="1",
            package_format="rpm",
            install_dir="_internal/porting_cli",
            enabled=False,
        ),
    ]


def _runtime():
    return RuntimeConfig(
        download_defaults=DownloadDefaults(base_url="https://example.com"),
        verify_defaults=VerifyDefaults(),
        packages=_packages(),
    )


def test_get_packages_by_name_case_insensitive():
    matches = get_packages_by_name("devkit-porting-advisor", _packages())
    assert len(matches) == 1
    assert matches[0].product == "DevKit-Porting-Advisor"


def test_get_packages_by_name_not_found():
    with pytest.raises(ConfigError):
        get_packages_by_name("unknown", _packages())


def test_select_packages_requires_name():
    with pytest.raises(ConfigError, match="--name"):
        select_packages(None, _runtime())


def test_run_with_builtin_config_requires_name():
    with pytest.raises(ConfigError, match="--name"):
        run_with_builtin_config(name=None)
