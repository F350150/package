from pathlib import Path

import pytest

from package_manager.errors import ConfigError
from package_manager.install_state import get_installed_version, load_install_state, update_install_state


def test_load_install_state_invalid_yaml_raises(tmp_path: Path):
    state = tmp_path / ".install_state.yaml"
    state.write_text("products: [", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_install_state(state)


def test_update_install_state_then_get_version(tmp_path: Path):
    state = tmp_path / ".install_state.yaml"

    update_install_state(
        product="demo",
        version="1.2.3",
        package_format="rpm",
        path=state,
    )

    assert get_installed_version("demo", path=state) == "1.2.3"
