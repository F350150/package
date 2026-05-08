import pytest

from package_manager.errors import ConfigError
from package_manager.models import PackageConfig
from package_manager.service import get_package_by_id, get_packages_by_name, run_with_builtin_config


def _packages():
    return [
        PackageConfig(
            product="tiancheng",
            version="1",
            package_format="tar.gz",
            enabled=True,
        ),
        PackageConfig(
            product="tiancheng",
            version="1",
            package_format="rpm",
            enabled=False,
        ),
    ]


def test_get_packages_by_name_case_insensitive():
    matches = get_packages_by_name("TIANCHENG", _packages())
    assert len(matches) == 1
    assert matches[0].product == "tiancheng"


def test_get_packages_by_name_not_found():
    with pytest.raises(ConfigError):
        get_packages_by_name("unknown", _packages())


def test_get_package_by_id_found(monkeypatch):
    monkeypatch.setattr("package_manager.resolver.detect_runtime_arch", lambda: "x86_64")
    pkg = get_package_by_id("tiancheng-linux-x86_64-tar-gz", _packages())
    assert pkg.product == "tiancheng"


def test_get_package_by_id_not_found():
    with pytest.raises(ConfigError):
        get_package_by_id("missing", _packages())


def test_run_with_builtin_config_rejects_name_and_id():
    with pytest.raises(ConfigError):
        run_with_builtin_config(name="a", package_id="b")
