import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.main import app
from app.database import Base, get_db
import uuid

# Test database setup
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

TestingSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


@pytest.fixture(scope="function")
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client(setup_db):
    app.dependency_overrides[get_db] = override_get_db
    client = AsyncClient(app=app, base_url="http://test")
    return client


@pytest.mark.asyncio
async def test_create_profile_success(client):
    """Test successful profile creation."""
    response = await client.post("/api/profiles", json={"name": "ella"})
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "success"
    assert "data" in data
    assert data["data"]["name"] == "ella"


@pytest.mark.asyncio
async def test_create_profile_duplicate(client):
    """Test duplicate profile handling."""
    response1 = await client.post("/api/profiles", json={"name": "ella"})
    assert response1.status_code == 201
    profile_id_1 = response1.json()["data"]["id"]

    response2 = await client.post("/api/profiles", json={"name": "ella"})
    assert response2.status_code == 200
    assert response2.json()["message"] == "Profile already exists"
    assert response2.json()["data"]["id"] == profile_id_1


@pytest.mark.asyncio
async def test_create_profile_empty_name(client):
    """Test creation with empty name."""
    response = await client.post("/api/profiles", json={"name": ""})
    assert response.status_code == 400
    assert response.json()["status"] == "error"


@pytest.mark.asyncio
async def test_create_profile_missing_name(client):
    """Test creation with missing name field."""
    response = await client.post("/api/profiles", json={})
    assert response.status_code == 422
    assert response.json()["status"] == "error"


@pytest.mark.asyncio
async def test_get_profile_by_id(client):
    """Test retrieving profile by ID."""
    create_response = await client.post("/api/profiles", json={"name": "john"})
    profile_id = create_response.json()["data"]["id"]

    response = await client.get(f"/api/profiles/{profile_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["id"] == profile_id


@pytest.mark.asyncio
async def test_get_profile_not_found(client):
    """Test retrieving non-existent profile."""
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/api/profiles/{fake_id}")
    assert response.status_code == 404
    assert response.json()["status"] == "error"


@pytest.mark.asyncio
async def test_list_profiles(client):
    """Test listing all profiles."""
    await client.post("/api/profiles", json={"name": "ella"})
    await client.post("/api/profiles", json={"name": "john"})

    response = await client.get("/api/profiles")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["count"] >= 2


@pytest.mark.asyncio
async def test_delete_profile(client):
    """Test deleting a profile."""
    create_response = await client.post("/api/profiles", json={"name": "ella"})
    profile_id = create_response.json()["data"]["id"]

    delete_response = await client.delete(f"/api/profiles/{profile_id}")
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/profiles/{profile_id}")
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_profile_not_found(client):
    """Test deleting non-existent profile."""
    fake_id = str(uuid.uuid4())
    response = await client.delete(f"/api/profiles/{fake_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_health_check(client):
    """Test health check endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
