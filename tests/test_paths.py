from pathlib import Path

import pytest

from package_manager.errors import ConfigError
from package_manager.paths import CERT_FILENAME, root_ca_path


def test_root_ca_path_returns_internal_ca_when_exists(monkeypatch, tmp_path: Path):
    openssl_pems = tmp_path / "openssl" / "pems"
    openssl_pems.mkdir(parents=True)
    ca = openssl_pems / CERT_FILENAME
    ca.write_text("pem", encoding="utf-8")

    monkeypatch.setattr("package_manager.paths.internal_dir", lambda: tmp_path)
    assert root_ca_path() == ca


def test_root_ca_path_missing_raises(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("package_manager.paths.internal_dir", lambda: tmp_path)
    with pytest.raises(ConfigError, match="Internal root CA file does not exist"):
        root_ca_path()

