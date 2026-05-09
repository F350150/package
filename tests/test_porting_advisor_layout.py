from package_manager.installers import (
    detect_porting_advisor_payload_dir,
    has_porting_advisor_payload_archives,
    has_porting_advisor_runtime_layout,
    install_porting_advisor_runtime_layout,
)


def test_detect_porting_advisor_payload_layout(tmp_path):
    payload = tmp_path / "DevKit-Porting-Advisor-26.0.RC1-Linux-Kunpeng"
    payload.mkdir(parents=True)
    (payload / "Sql-Analysis-26.0.RC1-Linux-Kunpeng.tar.gz").write_bytes(b"x")
    (payload / "jre-linux-aarch64.tar.gz").write_bytes(b"x")

    assert has_porting_advisor_payload_archives(payload) is True
    assert detect_porting_advisor_payload_dir(tmp_path) == payload


def test_install_porting_advisor_runtime_layout(tmp_path):
    payload = tmp_path / "payload"
    install_dir = tmp_path / "install"
    payload.mkdir(parents=True)
    install_dir.mkdir(parents=True)

    (payload / "Sql-Analysis-26.0.RC1-Linux-Kunpeng").mkdir(parents=True)
    (payload / "Sql-Analysis-26.0.RC1-Linux-Kunpeng" / "config").mkdir(parents=True)
    (payload / "Sql-Analysis-26.0.RC1-Linux-Kunpeng" / "sql-analysis-26.0.RC1.jar").write_bytes(b"jar")
    (payload / "jre").mkdir(parents=True)
    (payload / "jre" / "bin").mkdir(parents=True)

    (payload / "Sql-Analysis-26.0.RC1-Linux-Kunpeng.tar.gz").write_bytes(b"x")
    (payload / "jre-linux-aarch64.tar.gz").write_bytes(b"x")

    def fake_extract_tar(package_path, install_path):
        return None

    # 只验证安装器产物拷贝逻辑，不依赖真实 tar 解压。
    import package_manager.installers as installers

    original = installers.extract_tar_package
    installers.extract_tar_package = fake_extract_tar
    try:
        install_porting_advisor_runtime_layout(payload, install_dir)
    finally:
        installers.extract_tar_package = original

    assert has_porting_advisor_runtime_layout(install_dir) is True
