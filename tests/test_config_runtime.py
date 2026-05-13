from pathlib import Path

import pytest

from package_manager.config import get_runtime_config
from package_manager.errors import ConfigError


def test_get_runtime_config_invalid_yaml_raises(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "packages.yaml"
    cfg.write_text("download_defaults: [", encoding="utf-8")
    monkeypatch.setenv("PACKAGE_MANAGER_CONFIG_FILE", str(cfg))

    with pytest.raises(ConfigError):
        get_runtime_config(reload=True)


def test_get_runtime_config_missing_required_field_raises(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "packages.yaml"
    cfg.write_text(
        """
download_defaults:
  base_url: "https://example.com"
verify_defaults:
  signature_format: "DER"
packages:
  - version: "1.0"
    artifact_version: "1.0"
    package_format: "tar.gz"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PACKAGE_MANAGER_CONFIG_FILE", str(cfg))

    with pytest.raises(ConfigError):
        get_runtime_config(reload=True)


def test_get_runtime_config_supported_versions_mismatch_raises(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "packages.yaml"
    cfg.write_text(
        """
download_defaults:
  base_url: "https://example.com"
verify_defaults:
  signature_format: "DER"
packages:
  - product: "demo"
    version: "2.0"
    artifact_version: "2.0.1"
    supported_versions: ["1.0"]
    package_format: "tar.gz"
    install_dir: "_internal/demo"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PACKAGE_MANAGER_CONFIG_FILE", str(cfg))

    with pytest.raises(ConfigError, match="project version"):
        get_runtime_config(reload=True)


def test_get_runtime_config_invalid_rpm_arch_separator_raises(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "packages.yaml"
    cfg.write_text(
        """
download_defaults:
  base_url: "https://example.com/"
verify_defaults:
  signature_format: "DER"
packages:
  - product: "demo"
    version: "1.0"
    artifact_version: "1.0"
    package_format: "rpm"
    rpm_arch_separator: "_"
    install_dir: "_internal/demo"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PACKAGE_MANAGER_CONFIG_FILE", str(cfg))

    with pytest.raises(ConfigError, match="rpm_arch_separator"):
        get_runtime_config(reload=True)


def test_get_runtime_config_field_aliases_not_supported(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "packages.yaml"
    cfg.write_text(
        """
download_defaults:
  base_url: "https://example.com/"
verify_defaults:
  signature_format: "DER"
field_aliases:
  package:
    project_version: "proj_ver"
packages:
  - product: "demo"
    project_version: "1.2.3"
    artifact_version: "1.2.3-7"
    package_format: "rpm"
    supported_versions: ["1.2.3"]
    install_dir: "_internal/demo"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PACKAGE_MANAGER_CONFIG_FILE", str(cfg))

    with pytest.raises(ConfigError, match="field_aliases is no longer supported"):
        get_runtime_config(reload=True)


def test_get_runtime_config_legacy_version_key_supported(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "packages.yaml"
    cfg.write_text(
        """
download_defaults:
  base_url: "https://example.com/"
verify_defaults:
  signature_format: "DER"
packages:
  - product: "demo"
    version: "1.2.3"
    artifact_version: "1.2.3-7"
    package_format: "tar.gz"
    supported_versions: ["1.2.3"]
    install_dir: "_internal/demo"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PACKAGE_MANAGER_CONFIG_FILE", str(cfg))

    runtime = get_runtime_config(reload=True)
    assert runtime.packages[0].version == "1.2.3"


def test_get_runtime_config_missing_install_dir_raises(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "packages.yaml"
    cfg.write_text(
        """
download_defaults:
  base_url: "https://example.com/"
verify_defaults:
  signature_format: "DER"
packages:
  - product: "demo"
    project_version: "1.2.3"
    artifact_version: "1.2.3-7"
    package_format: "tar.gz"
    supported_versions: ["1.2.3"]
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PACKAGE_MANAGER_CONFIG_FILE", str(cfg))

    with pytest.raises(ConfigError, match="install_dir"):
        get_runtime_config(reload=True)


def test_get_runtime_config_invalid_cache_policy_raises(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "packages.yaml"
    cfg.write_text(
        """
download_defaults:
  base_url: "https://example.com/"
  cache_policy: "unknown"
verify_defaults:
  signature_format: "DER"
packages:
  - product: "demo"
    project_version: "1.2.3"
    artifact_version: "1.2.3-7"
    package_format: "tar.gz"
    supported_versions: ["1.2.3"]
    install_dir: "_internal/demo"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PACKAGE_MANAGER_CONFIG_FILE", str(cfg))

    with pytest.raises(ConfigError, match="cache_policy"):
        get_runtime_config(reload=True)
