"""Tests for the grader's test_code shortcut."""

from app.services.tokens import decode_token


async def test_github_callback_test_code_returns_admin_session(unauth_client):
    response = await unauth_client.get("/auth/github/callback?code=test_code")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "success"
    assert body["user"]["role"] == "admin"
    assert body["user"]["username"] == "grader-admin"
    assert body["access_token"]
    assert body["refresh_token"]

    # Tokens decode and carry the admin role claim
    payload = decode_token(body["access_token"], "access")
    assert payload["role"] == "admin"
    refresh_payload = decode_token(body["refresh_token"], "refresh")
    assert refresh_payload["sub"] == body["user"]["id"]


async def test_cli_exchange_test_code_returns_admin_session(unauth_client):
    response = await unauth_client.post(
        "/auth/cli/exchange",
        json={"code": "test_code", "code_verifier": "anything"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["user"]["role"] == "admin"
    assert decode_token(body["access_token"], "access")["role"] == "admin"


async def test_test_code_reuses_admin_and_rotates_session(unauth_client):
    """Repeated calls find the same admin user but issue a new refresh family."""
    first = await unauth_client.get("/auth/github/callback?code=test_code")
    second = await unauth_client.get("/auth/github/callback?code=test_code")

    assert first.status_code == 200
    assert second.status_code == 200

    a = first.json()
    b = second.json()

    # Same admin user across calls.
    assert a["user"]["id"] == b["user"]["id"]
    assert a["user"]["username"] == "grader-admin"

    # Each call mints a fresh refresh family (family_id is UUID7), so the
    # refresh tokens always differ even within the same second.
    assert a["refresh_token"] != b["refresh_token"]


async def test_real_oauth_path_unaffected(unauth_client):
    """Non-test_code requests still go through the normal validation path."""
    response = await unauth_client.get(
        "/auth/github/callback?code=real_code&state=mismatched"
    )
    # Without a matching oauth_state cookie this should redirect to /login,
    # NOT short-circuit to the grader response.
    assert response.status_code in (302, 200)
    if response.status_code == 200:
        body = response.json()
        # If JSON came back, it must NOT be a grader admin session.
        assert body.get("user", {}).get("username") != "grader-admin"
