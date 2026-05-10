import subprocess

import pytest

from package_manager.errors import SignatureVerifyError
from package_manager.verifier import verify_p7s_detached


@pytest.fixture(autouse=True)
def mock_builtin_openssl(monkeypatch, tmp_path):
    fake = tmp_path / "openssl"
    fake.write_text("", encoding="utf-8")
    fake.chmod(0o755)
    fake_lib_dir = tmp_path / "openssl-lib"
    fake_lib_dir.mkdir(parents=True)
    monkeypatch.setattr("package_manager.verifier.openssl_bin_path", lambda: fake)
    monkeypatch.setattr("package_manager.verifier.openssl_lib_dir", lambda: fake_lib_dir)


def test_verify_success(monkeypatch, tmp_path):
    pkg = tmp_path / "a.tar.gz"
    sig = tmp_path / "a.tar.gz.p7s"
    ca = tmp_path / "root.pem"
    pkg.write_bytes(b"x")
    sig.write_bytes(b"y")
    ca.write_text("pem")

    def fake_run(cmd, capture_output, text, env):
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("package_manager.verifier.subprocess.run", fake_run)
    verify_p7s_detached(pkg, sig, ca, "DER", True)


def test_verify_nonzero_raises(monkeypatch, tmp_path):
    pkg = tmp_path / "a.tar.gz"
    sig = tmp_path / "a.tar.gz.p7s"
    ca = tmp_path / "root.pem"
    pkg.write_bytes(b"x")
    sig.write_bytes(b"y")
    ca.write_text("pem")

    def fake_run(cmd, capture_output, text, env):
        return subprocess.CompletedProcess(cmd, 2, "", "bad")

    monkeypatch.setattr("package_manager.verifier.subprocess.run", fake_run)
    with pytest.raises(SignatureVerifyError):
        verify_p7s_detached(pkg, sig, ca, "DER", True)


def test_verify_chain_true_missing_ca_raises(tmp_path):
    pkg = tmp_path / "a.tar.gz"
    sig = tmp_path / "a.tar.gz.p7s"
    pkg.write_bytes(b"x")
    sig.write_bytes(b"y")

    with pytest.raises(SignatureVerifyError):
        verify_p7s_detached(pkg, sig, tmp_path / "missing.pem", "DER", True)


def test_verify_chain_false_contains_noverify(monkeypatch, tmp_path):
    pkg = tmp_path / "a.tar.gz"
    sig = tmp_path / "a.tar.gz.p7s"
    pkg.write_bytes(b"x")
    sig.write_bytes(b"y")

    captured = {}

    def fake_run(cmd, capture_output, text, env):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("package_manager.verifier.subprocess.run", fake_run)
    verify_p7s_detached(pkg, sig, tmp_path / "unused.pem", "DER", False)

    assert "-noverify" in captured["cmd"]


def test_verify_chain_true_contains_cafile_and_purpose(monkeypatch, tmp_path):
    pkg = tmp_path / "a.tar.gz"
    sig = tmp_path / "a.tar.gz.p7s"
    ca = tmp_path / "root.pem"
    pkg.write_bytes(b"x")
    sig.write_bytes(b"y")
    ca.write_text("pem")

    captured = {}

    def fake_run(cmd, capture_output, text, env):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("package_manager.verifier.subprocess.run", fake_run)
    verify_p7s_detached(pkg, sig, ca, "DER", True)

    assert "-CAfile" in captured["cmd"]
    assert "-purpose" in captured["cmd"]
    assert "any" in captured["cmd"]


def test_verify_missing_builtin_openssl_raises(monkeypatch, tmp_path):
    pkg = tmp_path / "a.tar.gz"
    sig = tmp_path / "a.tar.gz.p7s"
    ca = tmp_path / "root.pem"
    pkg.write_bytes(b"x")
    sig.write_bytes(b"y")
    ca.write_text("pem")

    monkeypatch.setattr("package_manager.verifier.openssl_bin_path", lambda: tmp_path / "missing-openssl")
    with pytest.raises(SignatureVerifyError, match="Built-in openssl does not exist"):
        verify_p7s_detached(pkg, sig, ca, "DER", True)


def test_verify_injects_builtin_openssl_lib_path(monkeypatch, tmp_path):
    pkg = tmp_path / "a.tar.gz"
    sig = tmp_path / "a.tar.gz.p7s"
    ca = tmp_path / "root.pem"
    pkg.write_bytes(b"x")
    sig.write_bytes(b"y")
    ca.write_text("pem")

    lib_dir = tmp_path / "openssl-lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("package_manager.verifier.openssl_lib_dir", lambda: lib_dir)
    monkeypatch.setattr("package_manager.verifier.platform.system", lambda: "Linux")

    captured = {}

    def fake_run(cmd, capture_output, text, env):
        captured["env"] = env
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("package_manager.verifier.subprocess.run", fake_run)
    verify_p7s_detached(pkg, sig, ca, "DER", True)

    assert "LD_LIBRARY_PATH" in captured["env"]
    assert captured["env"]["LD_LIBRARY_PATH"].split(":")[0] == str(lib_dir)


def test_verify_missing_builtin_openssl_lib_dir_raises(monkeypatch, tmp_path):
    pkg = tmp_path / "a.tar.gz"
    sig = tmp_path / "a.tar.gz.p7s"
    ca = tmp_path / "root.pem"
    pkg.write_bytes(b"x")
    sig.write_bytes(b"y")
    ca.write_text("pem")

    monkeypatch.setattr("package_manager.verifier.openssl_lib_dir", lambda: tmp_path / "missing-lib-dir")
    with pytest.raises(SignatureVerifyError, match="Built-in openssl lib directory does not exist"):
        verify_p7s_detached(pkg, sig, ca, "DER", True)
