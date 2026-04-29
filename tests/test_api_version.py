"""X-API-Version middleware enforcement."""


async def test_missing_version_header_returns_400(client):
    """No X-API-Version on /api/* should be rejected with the spec message."""
    response = await client.get("/api/profiles", headers={"X-API-Version": ""})
    # The default header gets sent; explicitly clear it by sending empty value.
    # Empty header value is missing per slowapi's perspective.
    # If httpx sends the empty header, middleware should treat it as missing.
    if response.status_code == 200:
        # Some HTTP clients drop empty-value headers. Use a fresh request without it.
        client.headers.pop("X-API-Version", None)
        response = await client.get("/api/profiles")
    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "API version header required"


async def test_wrong_version_returns_400(client):
    response = await client.get("/api/profiles", headers={"X-API-Version": "2"})
    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "error"
    assert "Unsupported API version" in body["message"]


async def test_correct_version_passes(client):
    """Default headers include X-API-Version: 1 — should reach the route."""
    response = await client.get("/api/profiles")
    assert response.status_code == 200


async def test_auth_endpoints_dont_require_version(unauth_client):
    """/auth/* is out of scope for the version requirement."""
    # This will return 401 (no token) — but NOT 400 from version middleware.
    response = await unauth_client.get(
        "/auth/me", headers={"X-API-Version": ""}
    )
    assert response.status_code in (401, 200)


async def test_health_doesnt_require_version(unauth_client):
    response = await unauth_client.get("/health")
    assert response.status_code == 200
