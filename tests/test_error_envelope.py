"""Verify the standard {status, message} error envelope is consistent."""


async def test_method_not_allowed_uses_standard_envelope(unauth_client):
    """GET on a POST-only route returns 405 with our error shape, not FastAPI's."""
    response = await unauth_client.get("/auth/logout")
    assert response.status_code == 405
    body = response.json()
    assert body["status"] == "error"
    assert "message" in body
    # Must NOT be FastAPI's default {"detail": "..."} shape
    assert "detail" not in body


async def test_404_uses_standard_envelope(unauth_client):
    response = await unauth_client.get("/api/nonexistent-route-here")
    assert response.status_code in (400, 404)  # 400 if api-version blocks first
    body = response.json()
    assert body["status"] == "error"
