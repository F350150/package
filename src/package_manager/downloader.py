"""下载模块。

特性：
1. .tmp 原子下载
2. 重试
3. 远端大小探测
4. 磁盘空间预检查
5. 大块流式写入（降低系统调用开销）
"""

import os
import shutil
import ssl
import urllib.request
from urllib.error import HTTPError
from pathlib import Path
import time
from typing import Optional

from package_manager.errors import DownloadError
from package_manager.paths import root_ca_path

COPY_BUFFER_SIZE = 8 * 1024 * 1024
MIN_FREE_SPACE_BYTES_UNKNOWN_SIZE = 500 * 1024 * 1024
LOW_FREE_SPACE_WARNING_BYTES = 1 * 1024 * 1024 * 1024
LOW_FREE_SPACE_WARNING_RATIO = 0.05
TLS_CA_FILE_ENV = "PACKAGE_MANAGER_TLS_CA_FILE"
TLS_INSECURE_ENV = "PACKAGE_MANAGER_TLS_INSECURE"


def build_ssl_context(ssl_verify: bool = False) -> ssl.SSLContext:
    """构造下载使用的 TLS 上下文。"""

    if not ssl_verify or os.getenv(TLS_INSECURE_ENV, "").strip().lower() in {"1", "true", "yes"}:
        print(f"WARNING: TLS certificate verification is disabled")
        return ssl._create_unverified_context()

    context = ssl.create_default_context()
    cert_path = root_ca_path()
    if cert_path.exists():
        context.load_verify_locations(cafile=str(cert_path))

    extra_ca_file = os.getenv(TLS_CA_FILE_ENV, "").strip()
    if extra_ca_file:
        context.load_verify_locations(cafile=extra_ca_file)

    return context


def open_url(url_or_request, timeout_seconds: int, ssl_verify: bool = False):
    """统一封装 urlopen，确保下载与 HEAD 都使用同一 TLS 配置。"""

    context = build_ssl_context(ssl_verify)
    return urllib.request.urlopen(url_or_request, timeout=timeout_seconds, context=context)


def download_file(url: str, destination: Path, timeout_seconds: int, retry: int, ssl_verify: bool = False) -> None:
    """下载单个文件，失败按 retry 重试。"""

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = temp_path(destination)
    remote_size = get_remote_file_size(url, timeout_seconds, ssl_verify)
    print_remote_size(url, remote_size)
    if can_skip_download(destination, remote_size):
        return
    ensure_disk_space(destination, remote_size)
    do_download_with_retry(url, destination, tmp_path, timeout_seconds, retry, ssl_verify, remote_size)


def temp_path(path: Path) -> Path:
    """返回下载临时文件路径。"""

    return Path(f"{path}.tmp")


def get_remote_file_size(url: str, timeout_seconds: int, ssl_verify: bool = False) -> Optional[int]:
    """通过 HEAD 请求获取 Content-Length。"""

    try:
        req = urllib.request.Request(url, method="HEAD")
        with open_url(req, timeout_seconds, ssl_verify) as response:
            value = response.headers.get("Content-Length")
    except Exception:
        return None
    return parse_content_length(value)


def parse_content_length(value: Optional[str]) -> Optional[int]:
    """解析 Content-Length 字段。"""

    if not value:
        return None
    if not value.isdigit():
        return None
    size = int(value)
    return size if size >= 0 else None


def print_remote_size(url: str, remote_size: Optional[int]) -> None:
    """打印远端大小探测结果。"""

    if remote_size is not None:
        print(f"Remote file size: {remote_size} bytes for {url}")


def can_skip_download(destination: Path, remote_size: Optional[int]) -> bool:
    """判断本地文件是否可直接复用。"""

    local_size = read_local_size(destination)
    if local_size <= 0:
        return False
    if remote_size is not None:
        if local_size != remote_size:
            return False
    print(f"Skip download because local file already exists: {destination}")
    return True


def read_local_size(destination: Path) -> int:
    """读取本地文件大小，不存在返回 0。"""

    if not destination.exists():
        return 0
    return destination.stat().st_size


def ensure_disk_space(destination: Path, expected_size: Optional[int]) -> None:
    """做下载前磁盘空间校验，并在低余量场景给出预警。"""

    usage = shutil.disk_usage(destination.parent)
    if expected_size is None:
        ensure_space_for_unknown_size(usage.free)
        return
    ensure_space_for_known_size(destination, usage.total, usage.free, expected_size)


def ensure_space_for_unknown_size(free_bytes: int) -> None:
    """远端大小未知时的保守空间策略。"""

    if free_bytes < MIN_FREE_SPACE_BYTES_UNKNOWN_SIZE:
        raise DownloadError(
            "Insufficient disk space for download with unknown remote size: "
            f"free={free_bytes} required_at_least={MIN_FREE_SPACE_BYTES_UNKNOWN_SIZE}"
        )


def ensure_space_for_known_size(destination: Path, total: int, free: int, expected_size: int) -> None:
    """远端大小已知时的空间策略。"""

    if free < expected_size:
        raise DownloadError(f"Insufficient disk space: free={free} package_size={expected_size}")
    remaining = free - expected_size
    warn_if_low_remaining_space(destination, total, remaining)


def warn_if_low_remaining_space(destination: Path, total: int, remaining: int) -> None:
    """当下载后剩余空间偏低时输出预警。"""

    low_by_bytes = remaining < LOW_FREE_SPACE_WARNING_BYTES
    low_by_ratio = total > 0 and (remaining / total) < LOW_FREE_SPACE_WARNING_RATIO
    if low_by_bytes or low_by_ratio:
        print(
            "WARNING: low disk space after download predicted: "
            f"remaining={remaining} total={total} destination={destination}"
        )


def do_download_with_retry(
    url: str,
    destination: Path,
    tmp_path: Path,
    timeout_seconds: int,
    retry: int,
    ssl_verify: bool = False,
    remote_size: Optional[int] = None,
) -> None:
    """执行带重试的下载流程。"""

    attempts = max(1, retry)
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            download_once(
                url,
                destination,
                tmp_path,
                timeout_seconds,
                attempt,
                attempts,
                ssl_verify,
                remote_size=remote_size,
            )
            return
        except Exception as exc:
            last_exc = exc
            print(f"Download failed for {url} (attempt {attempt}/{attempts}): {exc}")
    cleanup_tmp(tmp_path)
    raise DownloadError(f"Failed to download {url}: {last_exc}") from last_exc


def download_once(
    url: str,
    destination: Path,
    tmp_path: Path,
    timeout_seconds: int,
    attempt: int,
    attempts: int,
    ssl_verify: bool = False,
    remote_size: Optional[int] = None,
) -> None:
    """执行一次下载尝试。"""

    resume_from = validate_resume_tmp(tmp_path, remote_size)
    if remote_size is not None and resume_from == remote_size:
        tmp_path.replace(destination)
        print(f"Resume hit complete tmp file, reuse it directly: {destination}")
        return

    response, append_mode, effective_resume = open_download_stream(url, timeout_seconds, ssl_verify, resume_from, tmp_path)
    print_download_line(url, destination, attempt, attempts, effective_resume)
    with response:
        with tmp_path.open("ab" if append_mode else "wb") as dst:
            stream_copy(response, dst, remote_size=effective_total_size(read_content_length(response), effective_resume))
    ensure_non_empty(tmp_path, url)
    if remote_size is not None and tmp_path.stat().st_size != remote_size:
        raise DownloadError(
            f"Downloaded size mismatch for {url}: expected={remote_size} actual={tmp_path.stat().st_size}"
        )
    tmp_path.replace(destination)
    print(f"Download succeeded: {destination}")


def open_download_stream(url: str, timeout_seconds: int, ssl_verify: bool, resume_from: int, tmp_path: Path):
    """按是否断点续传打开下载流。"""

    if resume_from <= 0:
        return open_url(url, timeout_seconds, ssl_verify), False, 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={resume_from}-"})
    try:
        response = open_url(req, timeout_seconds, ssl_verify)
        status = response.getcode()
        if status == 206:
            return response, True, resume_from
        # 服务端忽略 Range，降级为全量下载。
        response.close()
        cleanup_tmp(tmp_path)
        return open_url(url, timeout_seconds, ssl_verify), False, 0
    except HTTPError as exc:
        # 416 表示 Range 不可用，尝试全量下载兜底。
        if exc.code == 416:
            cleanup_tmp(tmp_path)
            return open_url(url, timeout_seconds, ssl_verify), False, 0
        raise


def print_download_line(url: str, destination: Path, attempt: int, attempts: int, resume_from: int) -> None:
    """打印下载起始日志。"""

    if resume_from > 0:
        print(f"Downloading {url} -> {destination} (attempt {attempt}/{attempts}, resume_from={resume_from})")
        return
    print(f"Downloading {url} -> {destination} (attempt {attempt}/{attempts})")


def validate_resume_tmp(tmp_path: Path, remote_size: Optional[int]) -> int:
    """校验并返回断点续传偏移量。"""

    if not tmp_path.exists():
        return 0
    local = tmp_path.stat().st_size
    if local <= 0:
        cleanup_tmp(tmp_path)
        return 0
    if remote_size is not None and local > remote_size:
        cleanup_tmp(tmp_path)
        return 0
    return local


def effective_total_size(content_length: Optional[int], resume_from: int) -> Optional[int]:
    """计算用于进度展示的总大小。"""

    if content_length is None:
        return None
    return content_length + resume_from


def cleanup_tmp(tmp_path: Path) -> None:
    """清理残留临时文件。"""

    if tmp_path.exists():
        tmp_path.unlink(missing_ok=True)


def read_content_length(response) -> Optional[int]:
    """从响应头读取并解析 Content-Length。"""

    value = response.headers.get("Content-Length")
    return parse_content_length(value)


def stream_copy(src, dst, remote_size: Optional[int] = None) -> None:
    """以大块缓冲拷贝流，并输出下载进度。"""

    downloaded = 0
    started_at = time.time()
    last_print = 0.0
    while True:
        chunk = src.read(COPY_BUFFER_SIZE)
        if not chunk:
            if remote_size:
                print()
            return
        dst.write(chunk)
        downloaded += len(chunk)
        now = time.time()
        if remote_size and (now - last_print >= 0.2 or downloaded >= remote_size):
            print_progress(downloaded, remote_size, started_at)
            last_print = now


def print_progress(downloaded: int, total: int, started_at: float) -> None:
    """输出单行下载进度条。"""

    percent = min(100, int(downloaded * 100 / total)) if total > 0 else 0
    bar_width = 70
    filled = int(bar_width * percent / 100)
    bar = "=" * max(0, filled - 1) + (">" if filled > 0 and percent < 100 else "=") + " " * (bar_width - filled)
    elapsed = max(0.001, time.time() - started_at)
    speed = downloaded / elapsed
    eta = int((total - downloaded) / speed) if speed > 0 else 0
    print(
        f"\r{percent}%[{bar}] {downloaded / (1024 * 1024):.2f}M "
        f"{speed / (1024 * 1024):.1f}MB/s eta {eta // 60}m {eta % 60}s",
        end="",
        flush=True,
    )


def ensure_non_empty(path: Path, url: str) -> None:
    """校验下载结果非空。"""

    if path.exists() and path.stat().st_size > 0:
        return
    raise DownloadError(f"Downloaded file is empty: {url}")
