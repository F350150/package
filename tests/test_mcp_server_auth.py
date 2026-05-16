import anyio

from package_manager.mcp_server import (
    CompositeTokenVerifier,
    HmacBearerTokenVerifier,
    StaticBearerTokenVerifier,
    build_server,
    issue_hmac_token,
    normalize_scopes,
    parse_args,
)


async def _verify(verifier, token: str):
    return await verifier.verify_token(token)


def test_static_bearer_token_verifier_accepts_configured_token():
    verifier = StaticBearerTokenVerifier(tokens=["abc123"], scopes=["pm:read"])
    token = anyio.run(_verify, verifier, "abc123")
    assert token is not None
    assert token.client_id == "opencode-static"
    assert token.scopes == ["pm:read"]


def test_static_bearer_token_verifier_rejects_unknown_token():
    verifier = StaticBearerTokenVerifier(tokens=["abc123"], scopes=["pm:read"])
    token = anyio.run(_verify, verifier, "wrong")
    assert token is None


def test_hmac_bearer_token_verifier_accepts_valid_token():
    secret = "test-secret"
    bearer = issue_hmac_token(secret=secret, client_id="client-A", scopes=["pm:read", "pm:write"], ttl_seconds=120)
    verifier = HmacBearerTokenVerifier(secret=secret)
    token = anyio.run(_verify, verifier, bearer)
    assert token is not None
    assert token.client_id == "client-A"
    assert set(token.scopes) == {"pm:read", "pm:write"}


def test_hmac_bearer_token_verifier_rejects_expired_token():
    secret = "test-secret"
    bearer = issue_hmac_token(secret=secret, client_id="client-A", scopes=["pm:read"], ttl_seconds=1)
    verifier = HmacBearerTokenVerifier(secret=secret)
    token = anyio.run(_verify, verifier, bearer)
    assert token is not None
    anyio.run(anyio.sleep, 1.2)
    expired = anyio.run(_verify, verifier, bearer)
    assert expired is None


def test_composite_verifier_works_with_static_and_hmac():
    secret = "test-secret"
    hmac_verifier = HmacBearerTokenVerifier(secret=secret)
    static_verifier = StaticBearerTokenVerifier(tokens=["legacy"], scopes=["pm:all"])
    verifier = CompositeTokenVerifier(verifiers=[hmac_verifier, static_verifier])
    bearer = issue_hmac_token(secret=secret, client_id="client-A", scopes=["pm:read"], ttl_seconds=120)
    from_hmac = anyio.run(_verify, verifier, bearer)
    from_static = anyio.run(_verify, verifier, "legacy")
    assert from_hmac is not None
    assert from_hmac.client_id == "client-A"
    assert from_static is not None
    assert from_static.client_id == "opencode-static"


def test_normalize_scopes():
    assert normalize_scopes("pm:read,pm:write,pm:read") == ["pm:read", "pm:write"]


def test_auth_disabled_nonlocal_is_blocked():
    args = parse_args(["--host", "0.0.0.0", "--auth-disabled"])
    try:
        build_server(args)
    except ValueError as exc:
        assert "auth-disabled on non-loopback host" in str(exc)
        return
    raise AssertionError("expected ValueError for non-loopback auth-disabled server")
