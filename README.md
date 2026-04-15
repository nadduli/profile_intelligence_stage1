# Profile Intelligence Service

A REST API that accepts a name, enriches it using three external APIs (Genderize, Agify, Nationalize), persists the result, and exposes endpoints to retrieve and manage stored profiles.

## Tech Stack

- **FastAPI** — async web framework
- **SQLAlchemy** (async) + **asyncpg** — database ORM and PostgreSQL driver
- **httpx** — async HTTP client for external API calls
- **UUID v7** — time-ordered unique IDs
- **Alembic** — database migrations

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd profile-intelligence-stage1
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your database URL
```

### 3. Run the server

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

## API Endpoints

### `POST /api/profiles`

Accepts a name, calls Genderize/Agify/Nationalize, stores and returns the enriched profile.

**Request:**
```json
{ "name": "ella" }
```

**Response (201):**
```json
{
  "status": "success",
  "data": {
    "id": "...",
    "name": "ella",
    "gender": "female",
    "gender_probability": 0.99,
    "sample_size": 1234,
    "age": 46,
    "age_group": "adult",
    "country_id": "DK",
    "country_probability": 0.12,
    "created_at": "2026-04-01T12:00:00Z"
  }
}
```

If the name already exists, returns the existing profile with `"message": "Profile already exists"` (HTTP 200).

### `GET /api/profiles/{id}`

Returns a single profile by UUID.

### `GET /api/profiles`

Returns all profiles. Supports optional case-insensitive filters:

- `?gender=female`
- `?country_id=NG`
- `?age_group=adult`

### `DELETE /api/profiles/{id}`

Deletes a profile. Returns `204 No Content`.

## Error Responses

All errors follow this structure:

```json
{ "status": "error", "message": "<description>" }
```

502 upstream failures:

```json
{ "status": "502", "message": "<API name> returned an invalid response" }
```

## Environment Variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string, e.g. `postgresql+asyncpg://user:pass@host/db` |
