"""Verify the custom RateLimitMiddleware enforces /auth/* limits."""

from app.middleware.rate_limit import AUTH_LIMIT


async def test_auth_endpoint_returns_429_after_limit(unauth_client):
    """AUTH_LIMIT requests succeed; the next one is 429 with standard envelope."""
    # Send AUTH_LIMIT successful pings to /auth/me (returns 401, but that's
    # still a valid response — the rate limiter counts it).
    for _ in range(AUTH_LIMIT):
        response = await unauth_client.get("/auth/me")
        assert response.status_code != 429, "Limit triggered too early"

    # The next request should be rate-limited.
    response = await unauth_client.get("/auth/me")
    assert response.status_code == 429
    body = response.json()
    assert body["status"] == "error"
    assert "rate limit" in body["message"].lower()
    assert response.headers.get("retry-after") == "60"
