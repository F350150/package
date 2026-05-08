import subprocess

import pytest

from package_manager.errors import SignatureVerifyError
from package_manager.verifier import verify_p7s_detached


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
