import io

import pytest

from package_manager.downloader import download_file
from package_manager.errors import DownloadError


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, headers=None, status: int = 200):
        super().__init__(data)
        self.headers = headers or {}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return self.status


def test_download_success(monkeypatch, tmp_path):
    dest = tmp_path / "a.bin"

    def fake_urlopen(req_or_url, timeout):
        assert timeout == 5
        if hasattr(req_or_url, "get_method") and req_or_url.get_method() == "HEAD":
            return FakeResponse(b"", headers={"Content-Length": "5"})
        return FakeResponse(b"hello", headers={"Content-Length": "5"})

    monkeypatch.setattr(
        "package_manager.downloader.open_url",
        lambda req_or_url, timeout_seconds, ssl_verify=False: fake_urlopen(req_or_url, timeout_seconds),
    )
    download_file("http://x/a.bin", dest, timeout_seconds=5, retry=1)
    assert dest.read_bytes() == b"hello"


def test_download_passes_ssl_verify(monkeypatch, tmp_path):
    dest = tmp_path / "a.bin"
    ssl_verify_values = []

    def fake_open_url(req_or_url, timeout_seconds, ssl_verify=False):
        assert timeout_seconds == 5
        ssl_verify_values.append(ssl_verify)
        if hasattr(req_or_url, "get_method") and req_or_url.get_method() == "HEAD":
            return FakeResponse(b"", headers={"Content-Length": "5"})
        return FakeResponse(b"hello", headers={"Content-Length": "5"})

    monkeypatch.setattr("package_manager.downloader.open_url", fake_open_url)

    download_file("http://x/a.bin", dest, timeout_seconds=5, retry=1, ssl_verify=True)

    assert dest.read_bytes() == b"hello"
    assert ssl_verify_values == [True, True]


def test_download_failure_cleans_tmp(monkeypatch, tmp_path):
    dest = tmp_path / "a.bin"

    def fake_urlopen(req_or_url, timeout):
        if hasattr(req_or_url, "get_method") and req_or_url.get_method() == "HEAD":
            return FakeResponse(b"", headers={"Content-Length": "5"})
        raise OSError("boom")

    monkeypatch.setattr(
        "package_manager.downloader.open_url",
        lambda req_or_url, timeout_seconds, ssl_verify=False: fake_urlopen(req_or_url, timeout_seconds),
    )

    with pytest.raises(DownloadError):
        download_file("http://x/a.bin", dest, timeout_seconds=5, retry=1)

    assert not (tmp_path / "a.bin.tmp").exists()


def test_download_empty_file_raises(monkeypatch, tmp_path):
    dest = tmp_path / "a.bin"

    def fake_urlopen(req_or_url, timeout):
        if hasattr(req_or_url, "get_method") and req_or_url.get_method() == "HEAD":
            return FakeResponse(b"", headers={"Content-Length": "1"})
        return FakeResponse(b"")

    monkeypatch.setattr(
        "package_manager.downloader.open_url",
        lambda req_or_url, timeout_seconds, ssl_verify=False: fake_urlopen(req_or_url, timeout_seconds),
    )

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

    monkeypatch.setattr(
        "package_manager.downloader.open_url",
        lambda req_or_url, timeout_seconds, ssl_verify=False: fake_urlopen(req_or_url, timeout_seconds),
    )
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

    ctx = build_ssl_context(ssl_verify=True)
    assert isinstance(ctx, FakeContext)
    assert loaded == [str(extra_ca)]


def test_build_ssl_context_supports_insecure_mode(monkeypatch):
    sentinel = object()
    monkeypatch.setenv("PACKAGE_MANAGER_TLS_INSECURE", "1")
    monkeypatch.setattr("package_manager.downloader.ssl._create_unverified_context", lambda: sentinel)

    from package_manager.downloader import build_ssl_context

    assert build_ssl_context() is sentinel


def test_download_resume_with_http_range(monkeypatch, tmp_path):
    dest = tmp_path / "a.bin"
    tmp_file = tmp_path / "a.bin.tmp"
    tmp_file.write_bytes(b"hello")
    seen_ranges = []

    def fake_open_url(req_or_url, timeout_seconds, ssl_verify=False):
        assert timeout_seconds == 5
        if hasattr(req_or_url, "get_method") and req_or_url.get_method() == "HEAD":
            return FakeResponse(b"", headers={"Content-Length": "10"})
        if hasattr(req_or_url, "headers"):
            seen_ranges.append(req_or_url.headers.get("Range", ""))
            return FakeResponse(b"world", headers={"Content-Length": "5"}, status=206)
        return FakeResponse(b"helloworld", headers={"Content-Length": "10"})

    monkeypatch.setattr("package_manager.downloader.open_url", fake_open_url)
    download_file("http://x/a.bin", dest, timeout_seconds=5, retry=1)

    assert dest.read_bytes() == b"helloworld"
    assert seen_ranges == ["bytes=5-"]
    assert not tmp_file.exists()


def test_download_resume_fallback_to_full_when_range_not_supported(monkeypatch, tmp_path):
    dest = tmp_path / "a.bin"
    tmp_file = tmp_path / "a.bin.tmp"
    tmp_file.write_bytes(b"hello")

    def fake_open_url(req_or_url, timeout_seconds, ssl_verify=False):
        assert timeout_seconds == 5
        if hasattr(req_or_url, "get_method") and req_or_url.get_method() == "HEAD":
            return FakeResponse(b"", headers={"Content-Length": "10"})
        if hasattr(req_or_url, "headers"):
            # 服务端忽略 Range，返回 200 全量
            return FakeResponse(b"helloworld", headers={"Content-Length": "10"}, status=200)
        return FakeResponse(b"helloworld", headers={"Content-Length": "10"}, status=200)

    monkeypatch.setattr("package_manager.downloader.open_url", fake_open_url)
    download_file("http://x/a.bin", dest, timeout_seconds=5, retry=1)

    assert dest.read_bytes() == b"helloworld"
    assert not tmp_file.exists()
