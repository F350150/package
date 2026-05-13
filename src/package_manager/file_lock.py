"""文件锁工具。

用于多进程场景下的文件级互斥访问。
"""

import json
import os
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

LOCK_TTL_SECONDS = 30 * 60
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.05


class FileLock:
    """基于原子创建锁文件的进程间排他锁。"""

    def __init__(
        self,
        lock_path: Path,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        stale_lock_ttl_seconds: int = LOCK_TTL_SECONDS,
    ):
        self.lock_path = lock_path
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.stale_lock_ttl_seconds = stale_lock_ttl_seconds
        self._fd: Optional[int] = None
        self._owner_token = ""

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._release()
        return False

    def _acquire(self) -> None:
        """获取排他锁，超时后抛出异常。"""

        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                self._owner_token = uuid.uuid4().hex
                payload = self._build_lock_payload(self._owner_token)
                os.write(fd, json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8"))
                os.fsync(fd)
                self._fd = fd
                return
            except FileExistsError:
                self._cleanup_stale_lock_if_needed()
                if time.monotonic() >= deadline:
                    holder = self._read_lock_meta_for_message()
                    raise TimeoutError(f"Acquire lock timeout: {self.lock_path}, holder={holder}")
                time.sleep(self.poll_interval)

    def _release(self) -> None:
        """释放排他锁。"""

        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if not self.lock_path.exists():
            return
        try:
            meta, inode = self._read_lock_meta()
        except OSError:
            return
        token = str(meta.get("token", "")).strip() if isinstance(meta, dict) else ""
        if token and token != self._owner_token:
            return
        try:
            current = self.lock_path.stat()
        except OSError:
            return
        if inode != current.st_ino:
            return
        self.lock_path.unlink(missing_ok=True)

    def _build_lock_payload(self, token: str) -> Dict[str, Any]:
        """构造锁文件元数据。"""

        return {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "created_at": time.time(),
            "start_token": self._process_start_token(os.getpid()),
            "token": token,
        }

    def _cleanup_stale_lock_if_needed(self) -> None:
        """判断锁是否陈旧，若陈旧则自动清理。"""

        try:
            meta, inode = self._read_lock_meta()
        except OSError:
            return
        stale, _reason = self._is_stale_lock(meta)
        if not stale:
            return
        try:
            current = self.lock_path.stat()
        except OSError:
            return
        if current.st_ino != inode:
            return
        self.lock_path.unlink(missing_ok=True)

    def _read_lock_meta_for_message(self) -> Dict[str, Any]:
        """读取锁元数据用于错误信息。"""

        try:
            meta, _ = self._read_lock_meta()
            return meta
        except OSError:
            return {"error": "unreadable"}

    def _read_lock_meta(self) -> Tuple[Dict[str, Any], int]:
        """读取锁文件元数据与 inode。"""

        stat = self.lock_path.stat()
        raw = self.lock_path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}, stat.st_ino
        parsed = self._parse_lock_meta(raw)
        return parsed, stat.st_ino

    @staticmethod
    def _parse_lock_meta(raw: str) -> Dict[str, Any]:
        """解析锁元数据，兼容历史纯 pid 格式。"""

        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
        if raw.isdigit():
            return {"pid": int(raw)}
        return {}

    def _is_stale_lock(self, meta: Dict[str, Any]) -> Tuple[bool, str]:
        """判定锁是否陈旧。"""

        pid = self._to_int(meta.get("pid"))
        host = str(meta.get("host", "")).strip()
        created_at = self._to_float(meta.get("created_at"))
        recorded_start = str(meta.get("start_token", "")).strip()
        current_host = socket.gethostname()

        if pid is not None and host and host == current_host:
            if not self._process_exists(pid):
                return True, "pid_not_alive"
            actual_start = self._process_start_token(pid)
            if recorded_start and actual_start and recorded_start != actual_start:
                return True, "pid_reused"
            return False, "process_alive"

        if created_at is not None and (time.time() - created_at) >= self.stale_lock_ttl_seconds:
            return True, "ttl_expired"
        return False, "fresh_or_unknown"

    @staticmethod
    def _process_exists(pid: int) -> bool:
        """判断进程是否存在。"""

        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    @staticmethod
    def _process_start_token(pid: int) -> str:
        """读取进程启动标识（Linux /proc stat 第 22 列）。"""

        stat_path = Path(f"/proc/{pid}/stat")
        if not stat_path.exists():
            return ""
        try:
            raw = stat_path.read_text(encoding="utf-8", errors="ignore")
            fields = raw.split()
            if len(fields) > 21:
                return fields[21]
        except OSError:
            return ""
        return ""

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        """安全转换 int。"""

        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        """安全转换 float。"""

        try:
            return float(value)
        except (TypeError, ValueError):
            return None
