import pytest
import pytest_asyncio
import uuid_extensions
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.middleware.rate_limit import RateLimitMiddleware
from app.models import Profile, User
from app.security.rate_limit import limiter
from app.services import query_cache
from app.services import users as user_service
from app.services.tokens import encode_access_token


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Wipe rate-limit + query-cache state between tests.

    - rate-limit buckets: cleared so per-test bursts don't bleed.
    - query cache: cleared so test_X's cached profile list doesn't
      leak into test_Y after Y resets the DB.
    - rate_limit_enabled is forced True for the duration of the test, so
      the suite mirrors production behaviour even when the dev .env has
      set RATE_LIMIT_ENABLED=false (used for benchmarking, not test runs).
    """
    settings = get_settings()
    original = settings.rate_limit_enabled
    settings.rate_limit_enabled = True
    limiter.enabled = True

    RateLimitMiddleware.reset()
    query_cache._cache.clear()
    user_service._user_cache.clear()
    yield
    RateLimitMiddleware.reset()
    query_cache._cache.clear()
    user_service._user_cache.clear()

    settings.rate_limit_enabled = original
    limiter.enabled = original

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL, echo=False, connect_args={"check_same_thread": False}
)

TestSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_db():
    """test database session"""
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest_asyncio.fixture
async def setup_db():
    """Create tables before each test, drop after. Keeps tests isolated."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _create_user(role: str, github_id: str, username: str) -> User:
    """Insert a user row into the test DB and return it."""
    user = User(
        id=uuid_extensions.uuid7(),
        github_id=github_id,
        username=username,
        email=f"{username}@test.local",
        avatar_url=None,
        role=role,
        is_active=True,
    )
    async with TestSessionLocal() as db:
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


def _auth_headers(user: User) -> dict[str, str]:
    """Bearer + X-API-Version headers for an authenticated request."""
    return {
        "Authorization": f"Bearer {encode_access_token(user.id, user.role)}",
        "X-API-Version": "1",
    }


@pytest_asyncio.fixture
async def admin_user(setup_db):
    return await _create_user("admin", "test-admin", "admin_test")


@pytest_asyncio.fixture
async def analyst_user(setup_db):
    return await _create_user("analyst", "test-analyst", "analyst_test")


@pytest_asyncio.fixture
async def client(admin_user):
    """Authenticated admin client. Default for tests that need full access.

    Sends X-API-Version: 1 and a valid bearer token on every request.
    """
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=_auth_headers(admin_user),
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def analyst_client(analyst_user):
    """Authenticated analyst client. For role-enforcement tests."""
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=_auth_headers(analyst_user),
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauth_client(setup_db):
    """No bearer token. For testing auth-required endpoints reject anonymous."""
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Version": "1"},
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_profiles(setup_db):
    """
    Insert known test profiles directly into DB.
    Does NOT call external APIs — safe, fast, deterministic.
    """
    async with TestSessionLocal() as db:
        profiles = [
            Profile(
                id=uuid_extensions.uuid7(),
                name="Alice Mensah",
                gender="female",
                gender_probability=0.99,
                age=28,
                age_group="adult",
                country_id="NG",
                country_name="Nigeria",
                country_probability=0.85,
            ),
            Profile(
                id=uuid_extensions.uuid7(),
                name="Kwame Osei",
                gender="male",
                gender_probability=0.95,
                age=17,
                age_group="teenager",
                country_id="GH",
                country_name="Ghana",
                country_probability=0.78,
            ),
            Profile(
                id=uuid_extensions.uuid7(),
                name="Fatima Diallo",
                gender="female",
                gender_probability=0.98,
                age=65,
                age_group="senior",
                country_id="SN",
                country_name="Senegal",
                country_probability=0.90,
            ),
            Profile(
                id=uuid_extensions.uuid7(),
                name="Emeka Eze",
                gender="male",
                gender_probability=0.92,
                age=35,
                age_group="adult",
                country_id="NG",
                country_name="Nigeria",
                country_probability=0.88,
            ),
            Profile(
                id=uuid_extensions.uuid7(),
                name="Amara Kamara",
                gender="male",
                gender_probability=0.88,
                age=8,
                age_group="child",
                country_id="KE",
                country_name="Kenya",
                country_probability=0.72,
            ),
        ]
        db.add_all(profiles)
        await db.commit()


@pytest_asyncio.fixture
async def client_with_data(seeded_profiles, admin_user):
    """Admin client with pre-seeded profiles."""
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=_auth_headers(admin_user),
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
