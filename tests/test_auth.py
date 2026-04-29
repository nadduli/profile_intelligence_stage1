"""Tests for the auth layer: tokens, /auth/me, get_current_user."""

import uuid

import jwt
import pytest

from app.services.tokens import (
    InvalidTokenTypeError,
    decode_token,
    encode_access_token,
    encode_refresh_token,
    hash_token,
)


def test_encode_decode_access_roundtrip():
    user_id = uuid.uuid4()
    token = encode_access_token(user_id, "admin")
    payload = decode_token(token, "access")
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_encode_decode_refresh_roundtrip():
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    token = encode_refresh_token(user_id, family_id)
    payload = decode_token(token, "refresh")
    assert payload["sub"] == str(user_id)
    assert payload["family_id"] == str(family_id)
    assert payload["type"] == "refresh"


def test_decode_with_wrong_type_raises():
    """An access token decoded as refresh must raise — type-mismatch defense."""
    access = encode_access_token(uuid.uuid4(), "analyst")
    with pytest.raises(InvalidTokenTypeError):
        decode_token(access, "refresh")


def test_decode_garbage_raises():
    with pytest.raises(jwt.InvalidTokenError):
        decode_token("not.a.real.jwt", "access")


def test_hash_token_is_deterministic_64_hex():
    h1 = hash_token("the same input")
    h2 = hash_token("the same input")
    assert h1 == h2
    assert len(h1) == 64
    int(h1, 16)  # raises if not hex


def test_hash_token_differs_for_different_input():
    assert hash_token("a") != hash_token("b")


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------


async def test_me_returns_authenticated_user(client, admin_user):
    """/auth/me should return the currently authenticated user."""
    response = await client.get("/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == admin_user.username
    assert data["role"] == "admin"
    assert data["is_active"] is True


async def test_me_unauthenticated_returns_401(unauth_client):
    response = await unauth_client.get("/auth/me")
    assert response.status_code == 401


async def test_me_bad_bearer_returns_401(unauth_client):
    response = await unauth_client.get(
        "/auth/me", headers={"Authorization": "Bearer not.a.real.jwt"}
    )
    assert response.status_code == 401
