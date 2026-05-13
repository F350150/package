import json
import os
import socket
import time
from pathlib import Path

import pytest

from package_manager.file_lock import FileLock


def _write_lock_meta(path: Path, meta: dict) -> None:
    path.write_text(json.dumps(meta, ensure_ascii=True, sort_keys=True), encoding="utf-8")


def _find_non_existing_pid() -> int:
    pid = os.getpid() + 100000
    while True:
        try:
            os.kill(pid, 0)
            pid += 1
        except ProcessLookupError:
            return pid
        except PermissionError:
            pid += 1


def test_file_lock_reclaim_stale_lock_by_dead_pid(tmp_path: Path):
    lock_path = tmp_path / "demo.lock"
    _write_lock_meta(
        lock_path,
        {
            "pid": _find_non_existing_pid(),
            "host": socket.gethostname(),
            "created_at": time.time(),
            "start_token": "",
            "token": "stale",
        },
    )

    with FileLock(lock_path, timeout=1.0, poll_interval=0.01):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_file_lock_reclaim_stale_lock_by_ttl(tmp_path: Path):
    lock_path = tmp_path / "demo.lock"
    _write_lock_meta(
        lock_path,
        {
            "pid": 1,
            "host": "other-host",
            "created_at": time.time() - 3600,
            "start_token": "",
            "token": "stale",
        },
    )

    with FileLock(lock_path, timeout=1.0, poll_interval=0.01, stale_lock_ttl_seconds=10):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_file_lock_timeout_when_holder_alive(tmp_path: Path):
    lock_path = tmp_path / "demo.lock"
    _write_lock_meta(
        lock_path,
        {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "created_at": time.time(),
            "start_token": FileLock._process_start_token(os.getpid()),
            "token": "active",
        },
    )

    with pytest.raises(TimeoutError):
        with FileLock(lock_path, timeout=0.1, poll_interval=0.01, stale_lock_ttl_seconds=10):
            pass
