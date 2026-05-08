"""签名验证模块。"""

import os
import subprocess
from pathlib import Path
from typing import List

from package_manager.errors import SignatureVerifyError
from package_manager.paths import openssl_bin_path


def verify_p7s_detached(
    package_path: Path,
    signature_path: Path,
    root_ca: Path,
    signature_format: str,
    verify_chain: bool,
) -> None:
    """执行 CMS/PKCS#7 detached signature 验签。"""

    inform = normalize_inform(signature_format)
    ensure_root_ca_exists(root_ca, verify_chain)
    cmd = build_verify_command(package_path, signature_path, root_ca, inform, verify_chain)
    run_verify_command(cmd, package_path, signature_path)


def normalize_inform(signature_format: str) -> str:
    """规范化并校验签名格式。"""

    inform = signature_format.upper()
    if inform in {"DER", "PEM"}:
        return inform
    raise SignatureVerifyError(f"Unsupported signature format: {signature_format}")


def ensure_root_ca_exists(root_ca: Path, verify_chain: bool) -> None:
    """证书链校验开启时必须存在根证书文件。"""

    if not verify_chain:
        return
    if not root_ca.exists():
        raise SignatureVerifyError(f"Root CA file does not exist: {root_ca}")


def build_verify_command(
    package_path: Path,
    signature_path: Path,
    root_ca: Path,
    inform: str,
    verify_chain: bool,
) -> List[str]:
    """组装 openssl 验签命令。"""

    cmd = base_command(package_path, signature_path, inform)
    if verify_chain:
        cmd.extend(["-CAfile", str(root_ca), "-purpose", "any"])
    else:
        print("WARNING: certificate chain verification disabled")
        cmd.append("-noverify")
    cmd.extend(["-out", "/dev/null"])
    return cmd


def base_command(package_path: Path, signature_path: Path, inform: str) -> List[str]:
    """组装 openssl 的固定命令部分。"""

    openssl_cmd = resolve_openssl_command()
    return [
        openssl_cmd,
        "cms",
        "-verify",
        "-binary",
        "-inform",
        inform,
        "-in",
        str(signature_path),
        "-content",
        str(package_path),
    ]


def resolve_openssl_command() -> str:
    """优先使用内置 openssl，找不到则回退系统 openssl。"""

    path = openssl_bin_path()
    return str(path) if path.exists() else "openssl"


def run_verify_command(cmd: List[str], package_path: Path, signature_path: Path) -> None:
    """执行验签命令并处理结果。"""

    print(f"Running OpenSSL verify command for package={package_path} signature={signature_path}")
    env = os.environ.copy()
    env["OPENSSL_CONF"] = "/dev/null"
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    print(f"OpenSSL return code: {result.returncode}")
    if result.stderr:
        print(f"OpenSSL stderr: {result.stderr.strip()}")
    if result.returncode == 0:
        return
    stderr = result.stderr.strip()
    raise SignatureVerifyError(
        f"P7S verification failed for {package_path}, returncode={result.returncode}, stderr={stderr}"
    )
