"""Tests for the /api/users/me alias."""


async def test_users_me_returns_current_user(client, admin_user):
    response = await client.get("/api/users/me")
    assert response.status_code == 200

    body = response.json()
    assert body["username"] == admin_user.username
    assert body["role"] == "admin"


async def test_users_me_requires_auth(unauth_client):
    response = await unauth_client.get("/api/users/me")
    assert response.status_code == 401


async def test_users_me_requires_api_version_header(client):
    response = await client.get(
        "/api/users/me",
        headers={"X-API-Version": ""},
    )
    # Empty/missing API version header rejected by middleware
    assert response.status_code == 400
