"""下载模块。

特性：
1. .tmp 原子下载
2. 重试
3. 远端大小探测
4. 磁盘空间预检查
5. 大块流式写入（降低系统调用开销）
"""

import shutil
import urllib.request
from pathlib import Path
from typing import Optional

from package_manager.errors import DownloadError

COPY_BUFFER_SIZE = 8 * 1024 * 1024
MIN_FREE_SPACE_BYTES_UNKNOWN_SIZE = 500 * 1024 * 1024
LOW_FREE_SPACE_WARNING_BYTES = 1 * 1024 * 1024 * 1024
LOW_FREE_SPACE_WARNING_RATIO = 0.05


def download_file(url: str, destination: Path, timeout_seconds: int, retry: int) -> None:
    """下载单个文件，失败按 retry 重试。"""

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = temp_path(destination)
    remote_size = get_remote_file_size(url, timeout_seconds)
    print_remote_size(url, remote_size)
    if can_skip_download(destination, remote_size):
        return
    ensure_disk_space(destination, remote_size)
    do_download_with_retry(url, destination, tmp_path, timeout_seconds, retry)


def temp_path(path: Path) -> Path:
    """返回下载临时文件路径。"""

    return Path(f"{path}.tmp")


def get_remote_file_size(url: str, timeout_seconds: int) -> Optional[int]:
    """通过 HEAD 请求获取 Content-Length。"""

    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
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


def do_download_with_retry(url: str, destination: Path, tmp_path: Path, timeout_seconds: int, retry: int) -> None:
    """执行带重试的下载流程。"""

    attempts = max(1, retry)
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            download_once(url, destination, tmp_path, timeout_seconds, attempt, attempts)
            return
        except Exception as exc:
            last_exc = exc
            cleanup_tmp(tmp_path)
            print(f"Download failed for {url} (attempt {attempt}/{attempts}): {exc}")
    raise DownloadError(f"Failed to download {url}: {last_exc}") from last_exc


def download_once(
    url: str,
    destination: Path,
    tmp_path: Path,
    timeout_seconds: int,
    attempt: int,
    attempts: int,
) -> None:
    """执行一次下载尝试。"""

    cleanup_tmp(tmp_path)
    print(f"Downloading {url} -> {destination} (attempt {attempt}/{attempts})")
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        with tmp_path.open("wb") as dst:
            stream_copy(response, dst)
    ensure_non_empty(tmp_path, url)
    tmp_path.replace(destination)
    print(f"Download succeeded: {destination}")


def cleanup_tmp(tmp_path: Path) -> None:
    """清理残留临时文件。"""

    if tmp_path.exists():
        tmp_path.unlink(missing_ok=True)


def stream_copy(src, dst) -> None:
    """以大块缓冲拷贝流。"""

    while True:
        chunk = src.read(COPY_BUFFER_SIZE)
        if not chunk:
            return
        dst.write(chunk)


def ensure_non_empty(path: Path, url: str) -> None:
    """校验下载结果非空。"""

    if path.exists() and path.stat().st_size > 0:
        return
    raise DownloadError(f"Downloaded file is empty: {url}")
