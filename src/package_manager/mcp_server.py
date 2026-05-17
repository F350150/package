"""Remote MCP server for package-manager control plane."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import inspect
import json
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
try:
    from mcp.server.auth.settings import AuthSettings
except Exception:  # pragma: no cover - keep compatibility with older mcp versions
    AuthSettings = None  # type: ignore[assignment]

from package_manager.control_plane import ControlPlaneSettings, PackageManagerControlPlane


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "")
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class StaticBearerTokenVerifier(TokenVerifier):
    """Accept only configured static bearer tokens."""

    def __init__(self, tokens: Sequence[str], scopes: Sequence[str]):
        self._tokens = [token for token in tokens if token]
        self._scopes = normalize_scopes(scopes) or ["pm:all"]

    async def verify_token(self, token: str) -> AccessToken | None:
        for expected in self._tokens:
            if hmac.compare_digest(token, expected):
                return AccessToken(token=token, client_id="opencode-static", scopes=self._scopes)
        return None


class HmacBearerTokenVerifier(TokenVerifier):
    """Accept short-lived signed bearer tokens."""

    def __init__(self, secret: str):
        if not secret:
            raise ValueError("HMAC secret must not be empty")
        self._secret = secret.encode("utf-8")

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith("pmv1."):
            return None
        parts = token.split(".")
        if len(parts) != 3:
            return None
        _, payload_b64, signature_b64 = parts
        signing_input = f"pmv1.{payload_b64}".encode("utf-8")
        expected_sig = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        provided_sig = b64url_decode(signature_b64)
        if provided_sig is None or not hmac.compare_digest(provided_sig, expected_sig):
            return None
        payload_bytes = b64url_decode(payload_b64)
        if payload_bytes is None:
            return None
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        client_id = str(payload.get("client_id", "")).strip()
        scopes = normalize_scopes(payload.get("scopes", []))
        exp = payload.get("exp")
        if not client_id or not scopes or not isinstance(exp, int):
            return None
        if int(time.time()) >= exp:
            return None
        return AccessToken(token=token, client_id=client_id, scopes=scopes, expires_at=exp)


class CompositeTokenVerifier(TokenVerifier):
    """Try multiple verifiers until one succeeds."""

    def __init__(self, verifiers: Sequence[TokenVerifier]):
        self._verifiers = list(verifiers)

    async def verify_token(self, token: str) -> AccessToken | None:
        for verifier in self._verifiers:
            accepted = await verifier.verify_token(token)
            if accepted is not None:
                return accepted
        return None


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64url_decode(raw: str) -> Optional[bytes]:
    if not raw:
        return None
    padding = "=" * ((4 - len(raw) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(raw + padding)
    except Exception:
        return None


def normalize_scopes(scopes: Sequence[str] | str) -> list[str]:
    if isinstance(scopes, str):
        items = scopes.split(",")
    else:
        items = scopes
    result = sorted({str(item).strip() for item in items if str(item).strip()})
    return result


def issue_hmac_token(secret: str, client_id: str, scopes: Sequence[str], ttl_seconds: int = 3600) -> str:
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be > 0")
    payload = {
        "client_id": client_id,
        "scopes": normalize_scopes(scopes),
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
        "jti": os.urandom(8).hex(),
    }
    payload_b64 = b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"pmv1.{payload_b64}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"pmv1.{payload_b64}.{b64url_encode(signature)}"


def is_loopback_host(host: str) -> bool:
    normalized = (host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remote MCP server for package-manager")
    parser.add_argument("--host", default=os.getenv("PACKAGE_MANAGER_MCP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PACKAGE_MANAGER_MCP_PORT", "8800")))
    parser.add_argument("--path", default=os.getenv("PACKAGE_MANAGER_MCP_PATH", "/mcp"))
    parser.add_argument("--binary-path", default=os.getenv("PACKAGE_MANAGER_BINARY_PATH", ""))
    parser.add_argument("--config-file", default=os.getenv("PACKAGE_MANAGER_CONFIG_FILE", ""))
    parser.add_argument("--state-file", default=os.getenv("PACKAGE_MANAGER_INSTALL_STATE_FILE", ""))
    parser.add_argument("--token", default=os.getenv("PACKAGE_MANAGER_MCP_TOKEN", ""))
    parser.add_argument("--token-scopes", default=os.getenv("PACKAGE_MANAGER_MCP_TOKEN_SCOPES", "pm:all"))
    parser.add_argument("--hmac-secret", default=os.getenv("PACKAGE_MANAGER_MCP_HMAC_SECRET", ""))
    parser.add_argument("--public-base-url", default=os.getenv("PACKAGE_MANAGER_MCP_PUBLIC_BASE_URL", ""))
    parser.add_argument(
        "--stateless-http",
        action="store_true",
        default=env_flag("PACKAGE_MANAGER_MCP_STATELESS_HTTP", default=True),
        help="Use stateless streamable-http mode to avoid session-id coupling.",
    )
    parser.add_argument(
        "--auth-disabled",
        action="store_true",
        default=env_flag("PACKAGE_MANAGER_MCP_AUTH_DISABLED", default=False),
        help="Disable bearer auth checks (for local debug only).",
    )
    parser.add_argument(
        "--allow-auth-disabled-nonlocal",
        action="store_true",
        default=env_flag("PACKAGE_MANAGER_MCP_ALLOW_AUTH_DISABLED_NONLOCAL", default=False),
        help="Allow auth disabled even when host is non-loopback.",
    )
    return parser.parse_args(argv)


def default_public_base_url(host: str, port: int) -> str:
    normalized = (host or "").strip()
    if normalized in {"0.0.0.0", "::", "[::]"}:
        normalized = "127.0.0.1"
    return f"http://{normalized}:{int(port)}"


def fastmcp_supports(name: str) -> bool:
    try:
        return name in inspect.signature(FastMCP.__init__).parameters
    except Exception:
        return False


def build_control_plane(args: argparse.Namespace) -> PackageManagerControlPlane:
    settings = ControlPlaneSettings.from_env()
    if args.binary_path:
        settings = replace(settings, binary_path=Path(os.path.expanduser(args.binary_path)))
    if args.config_file:
        settings = replace(settings, config_file=Path(os.path.expanduser(args.config_file)))
    if args.state_file:
        settings = replace(settings, state_file=Path(os.path.expanduser(args.state_file)))
    return PackageManagerControlPlane(settings=settings)


def build_server(args: argparse.Namespace) -> FastMCP:
    control_plane = build_control_plane(args)
    token_verifier = None
    if not args.auth_disabled:
        verifiers: list[TokenVerifier] = []
        tokens = [token.strip() for token in args.token.split(",") if token.strip()]
        scopes = normalize_scopes(args.token_scopes)
        if tokens:
            verifiers.append(StaticBearerTokenVerifier(tokens=tokens, scopes=scopes))
        if args.hmac_secret.strip():
            verifiers.append(HmacBearerTokenVerifier(secret=args.hmac_secret.strip()))
        if not verifiers:
            raise ValueError(
                "auth enabled but no verifier configured, set --token/--token-scopes or --hmac-secret"
            )
        token_verifier = CompositeTokenVerifier(verifiers=verifiers)
    elif not is_loopback_host(args.host) and not args.allow_auth_disabled_nonlocal:
        raise ValueError(
            "auth-disabled on non-loopback host is blocked by default, set --allow-auth-disabled-nonlocal to override"
        )

    mcp_kwargs: Dict[str, Any] = {
        "name": "package-manager-mcp",
        "instructions": "Package management tools for install/status/health actions.",
        "host": args.host,
        "port": args.port,
        "streamable_http_path": args.path,
        "token_verifier": token_verifier,
        "log_level": "INFO",
    }
    if token_verifier is not None and AuthSettings is not None:
        public_base_url = (args.public_base_url or "").strip() or default_public_base_url(args.host, args.port)
        mcp_kwargs["auth"] = AuthSettings(
            issuer_url=public_base_url,
            resource_server_url=public_base_url,
            required_scopes=normalize_scopes(args.token_scopes) or ["pm:all"],
        )
    if args.stateless_http and fastmcp_supports("stateless_http"):
        mcp_kwargs["stateless_http"] = True
    mcp = FastMCP(**mcp_kwargs)

    def require_scope(required_scope: str) -> None:
        if args.auth_disabled:
            return
        access = get_access_token()
        if access is None:
            raise PermissionError("missing access token")
        scopes = {scope.strip() for scope in access.scopes if scope and scope.strip()}
        if "pm:all" in scopes or required_scope in scopes:
            return
        raise PermissionError(f"insufficient_scope: required={required_scope}, granted={sorted(scopes)}")

    def current_actor() -> str:
        if args.auth_disabled:
            return "auth-disabled"
        access = get_access_token()
        if access is None:
            return "unknown"
        return str(access.client_id or "unknown")

    @mcp.tool(name="pm_health", description="Check package-manager runtime health on remote host.")
    def pm_health() -> Dict[str, Any]:
        require_scope("pm:read")
        return control_plane.health()

    @mcp.tool(name="pm_list_packages", description="List enabled package products from runtime config.")
    def pm_list_packages() -> Dict[str, Any]:
        require_scope("pm:read")
        return control_plane.list_packages()

    @mcp.tool(name="pm_status", description="Read install state for all products or one product.")
    def pm_status(product: Optional[str] = None) -> Dict[str, Any]:
        require_scope("pm:read")
        return control_plane.status(product=product)

    @mcp.tool(
        name="pm_install",
        description=(
            "Low-level install primitive. Prefer pm_skill_install_guarded for user-facing install requests, "
            "especially when dry-run and final status confirmation are required."
        ),
    )
    def pm_install(product: str, dry_run: bool = False) -> Dict[str, Any]:
        require_scope("pm:write")
        return control_plane.install(product=product, dry_run=dry_run)

    @mcp.tool(
        name="pm_skill_install_guarded",
        description=(
            "Preferred install workflow for natural-language install intents: "
            "health -> list -> dry-run -> real install -> status."
        ),
    )
    def pm_skill_install_guarded(product: str) -> Dict[str, Any]:
        require_scope("pm:write")
        return control_plane.install_with_guardrails(product=product)

    @mcp.tool(name="pm_get_config", description="Read runtime package config (full or selected path/product).")
    def pm_get_config(path: Optional[str] = None, product: Optional[str] = None) -> Dict[str, Any]:
        require_scope("pm:read")
        return control_plane.get_config(path=path, product=product)

    @mcp.tool(
        name="pm_update_config_plan",
        description="Plan configuration changes and risk assessment. No state mutation.",
    )
    def pm_update_config_plan(operations: list[dict[str, Any]], reason: str = "") -> Dict[str, Any]:
        require_scope("pm:admin")
        return control_plane.update_config_plan(operations=operations, actor=current_actor(), reason=reason)

    @mcp.tool(
        name="pm_uninstall_plan",
        description="Plan package uninstall impact and risk. No state mutation.",
    )
    def pm_uninstall_plan(product: str, reason: str = "") -> Dict[str, Any]:
        require_scope("pm:admin")
        return control_plane.uninstall_plan(product=product, actor=current_actor(), reason=reason)

    @mcp.tool(
        name="pm_confirm_plan",
        description="Issue short-lived challenge token for a pending dangerous plan.",
    )
    def pm_confirm_plan(plan_id: str) -> Dict[str, Any]:
        require_scope("pm:admin")
        return control_plane.confirm_plan(plan_id=plan_id, actor=current_actor())

    @mcp.tool(
        name="pm_update_config_apply",
        description="Apply a planned config change with challenge token and idempotency key.",
    )
    def pm_update_config_apply(
        plan_id: str,
        challenge_token: str,
        idempotency_key: str,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        require_scope("pm:admin")
        req = (request_id or "").strip() or f"req-{os.urandom(6).hex()}"
        return control_plane.update_config_apply(
            plan_id=plan_id,
            challenge_token=challenge_token,
            request_id=req,
            idempotency_key=idempotency_key,
            actor=current_actor(),
        )

    @mcp.tool(
        name="pm_uninstall_apply",
        description="Apply a planned uninstall with challenge token and idempotency key.",
    )
    def pm_uninstall_apply(
        plan_id: str,
        challenge_token: str,
        idempotency_key: str,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        require_scope("pm:admin")
        req = (request_id or "").strip() or f"req-{os.urandom(6).hex()}"
        return control_plane.uninstall_apply(
            plan_id=plan_id,
            challenge_token=challenge_token,
            request_id=req,
            idempotency_key=idempotency_key,
            actor=current_actor(),
        )

    @mcp.tool(
        name="pm_rollback_config",
        description="Rollback config from a backup version id. Requires admin scope.",
    )
    def pm_rollback_config(version_id: str, idempotency_key: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        require_scope("pm:admin")
        req = (request_id or "").strip() or f"req-{os.urandom(6).hex()}"
        return control_plane.rollback_config(
            version_id=version_id,
            request_id=req,
            idempotency_key=idempotency_key,
            actor=current_actor(),
        )

    return mcp


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    server = build_server(args)
    server.run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
