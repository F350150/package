import tarfile
import zipfile
from pathlib import Path

from package_manager.installer.utils import (
    detect_porting_advisor_payload_dir,
    has_porting_advisor_modern_payload,
    install_porting_advisor_runtime_layout,
)


def _make_jre_tar(target: Path) -> None:
    tmp_root = target.parent / "_jre_tmp"
    (tmp_root / "jre" / "bin").mkdir(parents=True, exist_ok=True)
    (tmp_root / "jre" / "bin" / "java").write_text("fake-java", encoding="utf-8")
    with tarfile.open(target, "w:gz") as tf:
        tf.add(tmp_root / "jre", arcname="jre")


def _make_porting_zip(target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("porting/index.html", "<html>ok</html>")


def test_modern_payload_detection_and_install(tmp_path: Path):
    payload = tmp_path / "payload-modern"
    (payload / "config").mkdir(parents=True)
    (payload / "config" / "component_config.json").write_text("{}", encoding="utf-8")
    (payload / "cmd" / "bin").mkdir(parents=True)
    (payload / "cmd" / "bin" / "sql-analysis-25.3.0.jar").write_text("jar", encoding="utf-8")
    _make_jre_tar(payload / "jre-linux-aarch64.tar.gz")
    _make_porting_zip(payload / "porting.zip")

    assert has_porting_advisor_modern_payload(payload) is True
    assert detect_porting_advisor_payload_dir(payload) == payload

    install_dir = tmp_path / "install"
    install_dir.mkdir(parents=True, exist_ok=True)
    install_porting_advisor_runtime_layout(payload, install_dir)

    assert (install_dir / "config" / "component_config.json").exists()
    assert (install_dir / "cmd" / "bin" / "sql-analysis-25.3.0.jar").exists()
    assert (install_dir / "jre" / "bin" / "java").exists()
    assert (install_dir / "porting" / "index.html").exists()
