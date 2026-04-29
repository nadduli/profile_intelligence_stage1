"""Role enforcement on /api/profiles/* endpoints."""

import uuid


async def test_unauth_get_returns_401(unauth_client):
    response = await unauth_client.get("/api/profiles")
    assert response.status_code == 401


async def test_unauth_post_returns_401(unauth_client):
    response = await unauth_client.post("/api/profiles", json={"name": "x"})
    assert response.status_code == 401


async def test_unauth_delete_returns_401(unauth_client):
    fake_id = str(uuid.uuid4())
    response = await unauth_client.delete(f"/api/profiles/{fake_id}")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Analyst — read OK, write 403
# ---------------------------------------------------------------------------


async def test_analyst_can_list(analyst_client):
    response = await analyst_client.get("/api/profiles")
    assert response.status_code == 200


async def test_analyst_can_search(analyst_client):
    response = await analyst_client.get("/api/profiles/search?q=females")
    assert response.status_code == 200


async def test_analyst_can_view_stats(analyst_client):
    response = await analyst_client.get("/api/profiles/stats")
    assert response.status_code == 200


async def test_analyst_post_returns_403(analyst_client):
    response = await analyst_client.post("/api/profiles", json={"name": "Test"})
    assert response.status_code == 403


async def test_analyst_delete_returns_403(analyst_client):
    fake_id = str(uuid.uuid4())
    response = await analyst_client.delete(f"/api/profiles/{fake_id}")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Inactive user — 403 even with valid token
# ---------------------------------------------------------------------------


async def test_disabled_user_returns_403(client, admin_user):
    """An admin token where the DB row is_active=False returns 403, not 401."""
    from sqlalchemy import update

    from app.models import User
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        await db.execute(
            update(User).where(User.id == admin_user.id).values(is_active=False)
        )
        await db.commit()

    response = await client.get("/auth/me")
    assert response.status_code == 403
