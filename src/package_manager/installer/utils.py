"""安装器通用工具函数。"""

import shutil
import subprocess
from pathlib import Path

from package_manager.downloader import download_file
from package_manager.errors import ConfigError, DownloadError, InstallError
from package_manager.models import ResolvedPackage
from package_manager.paths import app_dir


def reset_install_dir(install_dir: Path) -> None:
    if install_dir.exists():
        shutil.rmtree(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)


def extract_tar_package(package_path: Path, install_dir: Path) -> None:
    extract = subprocess.run(["tar", "-xzf", str(package_path), "-C", str(install_dir)], capture_output=True, text=True)
    if extract.returncode == 0:
        return
    raise InstallError(f"tar extract failed: {extract.stderr.strip()}")


def run_optional_install_script(install_dir: Path) -> None:
    install_script = install_dir / "install.sh"
    if not install_script.exists():
        return
    result = subprocess.run(["bash", str(install_script)], cwd=str(install_dir), capture_output=True, text=True)
    if result.returncode == 0:
        return
    raise InstallError(f"install.sh failed: {result.stderr.strip()}")


def ensure_install_dir_exists(install_dir: Path) -> None:
    if install_dir.exists():
        return
    raise InstallError(f"Install directory missing after installation: {install_dir}")


def run_rpm_command(args):
    cmd = ["rpm", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise InstallError("rpm command not found in PATH on current host") from exc


def ensure_local_or_download(url: str, destination: Path, timeout_seconds: int, retry: int) -> None:
    if destination.exists() and destination.is_file() and destination.stat().st_size > 0:
        print(f"Use local artifact file: {destination}")
        return
    try:
        download_file(url, destination, timeout_seconds, retry)
    except DownloadError as exc:
        target_dir = destination.parent
        raise DownloadError(
            f"{exc}. Offline install hint: place file at '{destination}' "
            f"(directory: '{target_dir}') and rerun."
        ) from exc


def has_porting_advisor_runtime_layout(path: Path) -> bool:
    return (path / "config").exists() and (path / "jre").exists() and any(path.glob("sql-analysis-*.jar"))


def detect_porting_advisor_payload_dir(base_dir: Path) -> Path:
    if has_porting_advisor_payload_archives(base_dir):
        return base_dir
    candidates = sorted([item for item in base_dir.iterdir() if item.is_dir()], key=lambda item: item.name)
    for candidate in candidates:
        if has_porting_advisor_payload_archives(candidate):
            return candidate
    raise InstallError(f"No Porting-Advisor payload directory found under {base_dir}")


def has_porting_advisor_payload_archives(path: Path) -> bool:
    return any(path.glob("Sql-Analysis-*-Linux-Kunpeng.tar.gz")) and any(path.glob("jre-linux-*.tar.gz"))


def install_porting_advisor_runtime_layout(payload_dir: Path, install_dir: Path) -> None:
    sql_tar = first_match(payload_dir, "Sql-Analysis-*-Linux-Kunpeng.tar.gz")
    jre_tar = first_match(payload_dir, "jre-linux-*.tar.gz")
    extract_tar_package(sql_tar, payload_dir)
    extract_tar_package(jre_tar, payload_dir)

    sql_dir = first_child_dir_match(payload_dir, "Sql-Analysis-*")
    jar_file = first_match(sql_dir, "*.jar")
    if not (sql_dir / "config").exists():
        raise InstallError(f"Sql-Analysis config directory not found under {sql_dir}")
    if not (payload_dir / "jre").exists():
        raise InstallError(f"jre directory not found under {payload_dir}")

    shutil.copytree(sql_dir / "config", install_dir / "config")
    shutil.copytree(payload_dir / "jre", install_dir / "jre")
    shutil.copy2(jar_file, install_dir / jar_file.name)


def first_child_dir(path: Path, exclude: str = "") -> Path:
    for item in path.iterdir():
        if item.is_dir() and item.name != exclude:
            return item
    raise InstallError(f"No child directory found under {path}")


def first_match(path: Path, pattern: str) -> Path:
    matched = sorted(path.glob(pattern))
    if matched:
        return matched[0]
    raise InstallError(f"No file matched pattern={pattern} under {path}")


def first_child_dir_match(path: Path, pattern: str) -> Path:
    matched = sorted([item for item in path.glob(pattern) if item.is_dir()])
    if matched:
        return matched[0]
    raise InstallError(f"No directory matched pattern={pattern} under {path}")


def resolve_install_dir(resolved: ResolvedPackage) -> Path:
    configured = (resolved.config.install_dir or "").strip()
    if not configured:
        raise ConfigError(f"install_dir must be configured for product={resolved.config.product}")
    configured_path = Path(configured)
    if configured_path.is_absolute():
        return configured_path
    return app_dir() / configured_path
