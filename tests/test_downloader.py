import io

import pytest

from package_manager.downloader import download_file
from package_manager.errors import DownloadError


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_download_success(monkeypatch, tmp_path):
    dest = tmp_path / "a.bin"

    def fake_urlopen(req_or_url, timeout):
        assert timeout == 5
        if hasattr(req_or_url, "get_method") and req_or_url.get_method() == "HEAD":
            return FakeResponse(b"", headers={"Content-Length": "5"})
        return FakeResponse(b"hello", headers={"Content-Length": "5"})

    monkeypatch.setattr("package_manager.downloader.open_url", lambda req_or_url, timeout_seconds: fake_urlopen(req_or_url, timeout_seconds))
    download_file("http://x/a.bin", dest, timeout_seconds=5, retry=1)
    assert dest.read_bytes() == b"hello"


def test_download_failure_cleans_tmp(monkeypatch, tmp_path):
    dest = tmp_path / "a.bin"

    def fake_urlopen(req_or_url, timeout):
        if hasattr(req_or_url, "get_method") and req_or_url.get_method() == "HEAD":
            return FakeResponse(b"", headers={"Content-Length": "5"})
        raise OSError("boom")

    monkeypatch.setattr("package_manager.downloader.open_url", lambda req_or_url, timeout_seconds: fake_urlopen(req_or_url, timeout_seconds))

    with pytest.raises(DownloadError):
        download_file("http://x/a.bin", dest, timeout_seconds=5, retry=1)

    assert not (tmp_path / "a.bin.tmp").exists()


def test_download_empty_file_raises(monkeypatch, tmp_path):
    dest = tmp_path / "a.bin"

    def fake_urlopen(req_or_url, timeout):
        if hasattr(req_or_url, "get_method") and req_or_url.get_method() == "HEAD":
            return FakeResponse(b"", headers={"Content-Length": "1"})
        return FakeResponse(b"")

    monkeypatch.setattr("package_manager.downloader.open_url", lambda req_or_url, timeout_seconds: fake_urlopen(req_or_url, timeout_seconds))

    with pytest.raises(DownloadError):
        download_file("http://x/a.bin", dest, timeout_seconds=5, retry=1)


def test_download_insufficient_space_raises(monkeypatch, tmp_path):
    dest = tmp_path / "a.bin"

    def fake_urlopen(req_or_url, timeout):
        if hasattr(req_or_url, "get_method") and req_or_url.get_method() == "HEAD":
            return FakeResponse(b"", headers={"Content-Length": "1024"})
        return FakeResponse(b"hello", headers={"Content-Length": "5"})

    class FakeDisk:
        total = 1000
        used = 900
        free = 10

    monkeypatch.setattr("package_manager.downloader.open_url", lambda req_or_url, timeout_seconds: fake_urlopen(req_or_url, timeout_seconds))
    monkeypatch.setattr("package_manager.downloader.shutil.disk_usage", lambda _p: FakeDisk())

    with pytest.raises(DownloadError):
        download_file("http://x/a.bin", dest, timeout_seconds=5, retry=1)


def test_build_ssl_context_supports_extra_ca(monkeypatch, tmp_path):
    extra_ca = tmp_path / "extra-ca.pem"
    extra_ca.write_text("dummy")

    loaded = []

    class FakeContext:
        def load_verify_locations(self, cafile):
            loaded.append(cafile)

    monkeypatch.setattr("package_manager.downloader.ssl.create_default_context", lambda: FakeContext())
    monkeypatch.setattr("package_manager.downloader.root_ca_path", lambda: tmp_path / "missing.pem")
    monkeypatch.setenv("PACKAGE_MANAGER_TLS_CA_FILE", str(extra_ca))

    from package_manager.downloader import build_ssl_context

    ctx = build_ssl_context()
    assert isinstance(ctx, FakeContext)
    assert loaded == [str(extra_ca)]


def test_build_ssl_context_supports_insecure_mode(monkeypatch):
    sentinel = object()
    monkeypatch.setenv("PACKAGE_MANAGER_TLS_INSECURE", "1")
    monkeypatch.setattr("package_manager.downloader.ssl._create_unverified_context", lambda: sentinel)

    from package_manager.downloader import build_ssl_context

    assert build_ssl_context() is sentinel
