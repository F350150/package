#!/usr/bin/env python3
"""Download package artifacts locally and upload to remote via SSH/SCP."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage offline artifacts and upload via SSH/SCP")
    parser.add_argument("--manifest-file", required=True, help="Path to JSON manifest from pm_offline_manifest")
    parser.add_argument("--ssh-target", default="", help="SSH target like user@host")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH port")
    parser.add_argument("--ssh-key", default="", help="SSH private key path")
    parser.add_argument(
        "--docker-container",
        default="",
        help="Use docker transport for test env (copy files into this container instead of SSH/SCP).",
    )
    parser.add_argument("--local-cache-dir", default="/tmp/pm-offline-cache", help="Local cache root")
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, text=True)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def build_ssh_prefix(port: int, ssh_key: str) -> list[str]:
    args = ["ssh", "-p", str(port)]
    if ssh_key:
        args.extend(["-i", ssh_key])
    args.extend(["-o", "StrictHostKeyChecking=accept-new"])
    return args


def build_scp_prefix(port: int, ssh_key: str) -> list[str]:
    args = ["scp", "-P", str(port)]
    if ssh_key:
        args.extend(["-i", ssh_key])
    args.extend(["-o", "StrictHostKeyChecking=accept-new"])
    return args


def filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    if not name:
        raise ValueError(f"unable to parse filename from url: {url}")
    return name


def main() -> int:
    args = parse_args()
    if not args.ssh_target and not args.docker_container:
        raise SystemExit("either --ssh-target or --docker-container must be provided")
    manifest = json.loads(Path(args.manifest_file).read_text(encoding="utf-8"))
    package_url = str(manifest["package_url"])
    signature_url = str(manifest["signature_url"])
    remote_package_path = str(manifest["remote_package_path"])
    remote_signature_path = str(manifest["remote_signature_path"])

    product = str(manifest.get("product", "product"))
    cache_dir = Path(args.local_cache_dir) / product
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_package = cache_dir / filename_from_url(package_url)
    local_signature = cache_dir / filename_from_url(signature_url)

    print(f"[offline] downloading package: {package_url}")
    run(["curl", "-fL", package_url, "-o", str(local_package)])
    print(f"[offline] downloading signature: {signature_url}")
    run(["curl", "-fL", signature_url, "-o", str(local_signature)])

    remote_pkg_dir = str(Path(remote_package_path).parent)
    remote_sig_dir = str(Path(remote_signature_path).parent)
    if args.docker_container:
        container = args.docker_container
        print(f"[offline] ensure remote dirs via docker exec: {container}")
        run(
            [
                "docker",
                "exec",
                container,
                "/bin/sh",
                "-lc",
                f"mkdir -p '{remote_pkg_dir}' '{remote_sig_dir}'",
            ]
        )
        print(f"[offline] upload package via docker cp -> {remote_package_path}")
        run(["docker", "cp", str(local_package), f"{container}:{remote_package_path}"])
        print(f"[offline] upload signature via docker cp -> {remote_signature_path}")
        run(["docker", "cp", str(local_signature), f"{container}:{remote_signature_path}"])
    else:
        ssh_cmd = build_ssh_prefix(args.ssh_port, args.ssh_key) + [
            args.ssh_target,
            f"mkdir -p '{remote_pkg_dir}' '{remote_sig_dir}'",
        ]
        print(f"[offline] ensure remote dirs via ssh: {args.ssh_target}")
        run(ssh_cmd)

        scp_prefix = build_scp_prefix(args.ssh_port, args.ssh_key)
        print(f"[offline] upload package -> {remote_package_path}")
        run(scp_prefix + [str(local_package), f"{args.ssh_target}:{remote_package_path}"])
        print(f"[offline] upload signature -> {remote_signature_path}")
        run(scp_prefix + [str(local_signature), f"{args.ssh_target}:{remote_signature_path}"])

    print(
        json.dumps(
            {
                "status": "success",
                "product": product,
                "local_package": str(local_package),
                "local_signature": str(local_signature),
                "remote_package_path": remote_package_path,
                "remote_signature_path": remote_signature_path,
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
