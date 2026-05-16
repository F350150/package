#!/usr/bin/env python3
"""Generate a signed short-lived MCP bearer token."""

from __future__ import annotations

import argparse

from package_manager.mcp_server import issue_hmac_token, normalize_scopes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate HMAC bearer token for package-manager MCP server")
    parser.add_argument("--secret", required=True, help="HMAC shared secret")
    parser.add_argument("--client-id", default="opencode-client", help="Client identity")
    parser.add_argument("--scopes", default="pm:read,pm:write", help="Comma-separated scopes")
    parser.add_argument("--ttl-seconds", type=int, default=3600, help="Token TTL in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = issue_hmac_token(
        secret=args.secret,
        client_id=args.client_id,
        scopes=normalize_scopes(args.scopes),
        ttl_seconds=args.ttl_seconds,
    )
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
