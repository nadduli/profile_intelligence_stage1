# Profile Intelligence Service — Stage 2

A queryable demographic intelligence REST API built with FastAPI and PostgreSQL. It stores enriched profile data for 2026 individuals and exposes endpoints for advanced filtering, sorting, pagination, and natural language querying.

## Tech Stack

- **FastAPI** — async web framework
- **SQLAlchemy** (async) + **asyncpg** — ORM and PostgreSQL driver
- **PostgreSQL** — primary database
- **UUID v7** — time-ordered unique IDs
- **uv** — dependency management

## Database Schema

| Field                | Type         | Notes                              |
|----------------------|--------------|------------------------------------|
| id                   | UUID v7      | Primary key                        |
| name                 | VARCHAR      | Unique, person's full name         |
| gender               | VARCHAR      | `male` or `female`                 |
| gender_probability   | FLOAT        | Confidence score (0–1)             |
| age                  | INT          | Exact age                          |
| age_group            | VARCHAR      | `child`, `teenager`, `adult`, `senior` |
| country_id           | VARCHAR(2)   | ISO 3166-1 alpha-2 code (e.g. `NG`) |
| country_name         | VARCHAR      | Full country name                  |
| country_probability  | FLOAT        | Confidence score (0–1)             |
| created_at           | TIMESTAMP    | Auto-generated, UTC                |

## Local Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd profile-intelligence-stage1
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
# Set your DATABASE_URL in .env
```

Required environment variable:

| Variable       | Description                                                              |
|----------------|--------------------------------------------------------------------------|
| `DATABASE_URL` | PostgreSQL connection string e.g. `postgresql+asyncpg://user:pass@host/db` |

### 3. Seed the database

```bash
uv run python seed.py
```

This inserts all 2026 profiles. Re-running is safe — existing records are skipped via `ON CONFLICT DO NOTHING`.

### 4. Start the server

```bash
uv run uvicorn app.main:app --reload
```

API available at `http://localhost:8000`.

## API Endpoints

### `GET /api/profiles`

Returns a paginated list of profiles. Supports filtering, sorting, and pagination.

**Query Parameters:**

| Parameter               | Type   | Default      | Description                              |
|-------------------------|--------|--------------|------------------------------------------|
| `gender`                | string | —            | `male` or `female`                       |
| `age_group`             | string | —            | `child`, `teenager`, `adult`, `senior`   |
| `country_id`            | string | —            | ISO code e.g. `NG`, `KE`, `ZA`          |
| `min_age`               | int    | —            | Minimum age (inclusive)                  |
| `max_age`               | int    | —            | Maximum age (inclusive)                  |
| `min_gender_probability`| float  | —            | Minimum gender confidence score          |
| `min_country_probability`| float | —            | Minimum country confidence score         |
| `sort_by`               | string | `created_at` | `age`, `created_at`, `gender_probability`|
| `order`                 | string | `asc`        | `asc` or `desc`                          |
| `page`                  | int    | `1`          | Page number                              |
| `limit`                 | int    | `10`         | Results per page (max 50)                |

All filters are combinable — results must match all conditions.

**Example requests:**

```bash
# Males from Nigeria aged 25+
GET /api/profiles?gender=male&country_id=NG&min_age=25

# Adult females sorted by age descending
GET /api/profiles?gender=female&age_group=adult&sort_by=age&order=desc

# Page 2 with 20 results per page
GET /api/profiles?page=2&limit=20
```

**Response (200):**

```json
{
  "status": "success",
  "page": 1,
  "limit": 10,
  "total": 2026,
  "data": [
    {
      "id": "01966b3e-7c2a-7000-8f4e-1a2b3c4d5e6f",
      "name": "Awino Hassan",
      "gender": "female",
      "gender_probability": 0.66,
      "age": 68,
      "age_group": "senior",
      "country_id": "TZ",
      "country_name": "Tanzania",
      "country_probability": 0.6,
      "created_at": "2026-04-20T10:00:00Z"
    }
  ]
}
```

---

### `GET /api/profiles/search`

Natural language query endpoint. Converts plain English into filters and returns paginated results.

**Query Parameters:**

| Parameter | Type   | Required | Description               |
|-----------|--------|----------|---------------------------|
| `q`       | string | Yes      | Plain English query string |
| `page`    | int    | No       | Default: 1                |
| `limit`   | int    | No       | Default: 10, max: 50      |

**Supported query patterns:**

| Query example                        | Interpreted as                                          |
|--------------------------------------|---------------------------------------------------------|
| `young males`                        | `gender=male` + `min_age=16` + `max_age=24`             |
| `females above 30`                   | `gender=female` + `min_age=30`                          |
| `people from angola`                 | `country_id=AO`                                         |
| `adult males from kenya`             | `gender=male` + `age_group=adult` + `country_id=KE`     |
| `teenagers below 18`                 | `age_group=teenager` + `max_age=18`                     |
| `senior females from south africa`   | `gender=female` + `age_group=senior` + `country_id=ZA`  |

**Keyword mappings:**
- **Gender:** `male`, `female`
- **Age groups:** `child`, `teenager` / `teen`, `adult`, `senior` / `elderly` / `old`
- **"young":** maps to `min_age=16, max_age=24` (not a stored age group)
- **Age comparisons:** `above X` / `over X` → `min_age`, `below X` / `under X` → `max_age`
- **Countries:** full country name in English e.g. `nigeria`, `south africa`, `dr congo`

**Example requests:**

```bash
GET /api/profiles/search?q=young+males+from+nigeria
GET /api/profiles/search?q=females+above+30&page=2&limit=20
GET /api/profiles/search?q=adult+males+from+kenya
```

**Response (200 — success):**

```json
{
  "status": "success",
  "page": 1,
  "limit": 10,
  "total": 45,
  "data": [ ... ]
}
```

**Response (200 — uninterpretable query):**

```json
{
  "status": "error",
  "message": "Unable to interpret query"
}
```

---

### `GET /api/profiles/{id}`

Returns a single profile by UUID.

**Response (200):**

```json
{
  "status": "success",
  "data": { ... }
}
```

---

### `POST /api/profiles`

Creates a new profile by enriching a name via external APIs (Genderize, Agify, Nationalize).

**Request body:**

```json
{ "name": "Amara" }
```

**Response (201):**

```json
{
  "status": "success",
  "data": { ... }
}
```

If the name already exists, returns HTTP 200 with `"message": "Profile already exists"`.

---

### `DELETE /api/profiles/{id}`

Deletes a profile by UUID. Returns `204 No Content`.

---

## Error Responses

All errors follow this structure:

```json
{ "status": "error", "message": "<description>" }
```

| Status | Meaning                                      |
|--------|----------------------------------------------|
| 400    | Missing or invalid query parameter           |
| 404    | Profile not found                            |
| 422    | Invalid parameter type (e.g. non-integer age)|
| 500    | Internal server error                        |

## Natural Language Query — How It Works

The `/search` endpoint uses a **pure rule-based parser** — no AI or LLMs involved. It works as follows:

1. The query string is lowercased and stripped
2. Keywords are matched using string containment and regex patterns
3. Each matched keyword maps to a specific filter field
4. The resulting filter dict is passed directly to the same query engine used by `GET /api/profiles`
5. If no keywords are recognized, the parser returns `null` and the endpoint responds with `"Unable to interpret query"`

Multi-word country names (e.g. `south africa`, `dr congo`) are matched before single-word ones to avoid partial matches.

## Author
- **[Nadduli Daniel]** — [naddulidaniel94@gmail.com] - [GitHub](https://github.com/naddulidaniel) | [LinkedIn](https://linkedin.com/in/nadduli-daniel)

