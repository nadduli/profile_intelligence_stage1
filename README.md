# Insighta Labs+ — Backend

The backend service for **Insighta Labs+ (Stage 3)**: a secure, multi-interface
profile-intelligence platform. It exposes a FastAPI HTTP API consumed by two
separate clients — a CLI tool and a web portal — over a shared authentication
and authorization model.

> Stage 3 builds directly on Stage 2. All Stage 2 capabilities (filter, sort,
> paginate, natural-language search) are preserved unchanged.

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Tech Stack](#tech-stack)
- [Authentication Flow](#authentication-flow)
- [Token Handling](#token-handling)
- [Role Enforcement](#role-enforcement)
- [Natural Language Parsing](#natural-language-parsing)
- [API Reference](#api-reference)
- [CLI Usage](#cli-usage)
- [Local Setup](#local-setup)
- [Configuration](#configuration)
- [Database Schema](#database-schema)
- [Rate Limiting & Logging](#rate-limiting--logging)
- [Testing & CI](#testing--ci)
- [Deployment](#deployment)
- [Author](#author)

---

## System Architecture

Insighta Labs+ is split into three repositories that share one backend:

```
                ┌────────────────────────┐
                │      GitHub OAuth      │
                └──────────┬─────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
   ┌─────▼─────┐    ┌──────▼──────┐    ┌────▼──────┐
   │  insighta │    │ Web Portal  │    │  Backend  │
   │   CLI     │◀──▶│  (browser)  │◀──▶│  FastAPI  │
   │ (terminal)│    │             │    │ + Postgres│
   └───────────┘    └─────────────┘    └───────────┘
        │                                     ▲
        └─────────────────────────────────────┘
              same REST API, same data
```

Both clients hit the same `/auth/*` and `/api/*` surface. The backend is the
single source of truth for users, roles, sessions, and profile data.

### Backend layers

```
app/
├── main.py                     # FastAPI app, middleware stack, exception handlers
├── config.py                   # Pydantic settings loaded from .env
├── database.py                 # Async SQLAlchemy engine + Base model
├── models.py                   # Profile, User, RefreshToken
├── schemas.py                  # Pydantic request/response models
├── routers/
│   ├── auth.py                 # /auth/* — OAuth, refresh, logout, CLI exchange
│   └── profiles.py             # /api/profiles/* — CRUD, search, stats, export
├── services/
│   ├── enrichment.py           # Genderize / Agify / Nationalize fan-out
│   ├── github_oauth.py         # GitHub token exchange + user fetch
│   ├── profile.py              # Profile DB queries
│   ├── query_parser.py         # Rule-based NL → filter dict
│   ├── refresh_tokens.py       # Rotation + reuse detection
│   ├── tokens.py               # JWT encode/decode + SHA-256 hashing
│   └── users.py                # User upsert + lookup
├── security/
│   ├── deps.py                 # get_current_user, require_role
│   └── rate_limit.py           # SlowAPI keys (per-user / per-IP)
└── middleware/
    ├── api_version.py          # Enforces X-API-Version: 1
    ├── csrf.py                 # Double-submit cookie for cookie-auth requests
    └── request_logging.py      # method/path/status/duration + X-Request-ID
```

### Middleware order (request → response)

```
RequestLogging → APIVersion → CSRF → SlowAPI → CORS → GZip → routes
```

The logger wraps the entire stack so the recorded duration covers everything,
and a request ID is stamped on every response (`X-Request-ID`).

---

## Tech Stack

- **Python 3.12** + **FastAPI**
- **SQLAlchemy 2.0** (async) + **asyncpg** (Postgres driver)
- **Alembic** — schema migrations
- **PyJWT** — access/refresh tokens
- **SlowAPI** — rate limiting
- **httpx** — outbound HTTP (GitHub, enrichment APIs)
- **uv** — dependency management
- **ruff** — lint
- **pytest + pytest-asyncio + aiosqlite** — test suite

---

## Authentication Flow

The backend supports two distinct OAuth flows against the same user model:

### A. Web flow (browser)

```
   user                 web portal               backend                 github
    │                       │                      │                        │
    │  click "Login"        │                      │                        │
    │──────────────────────▶│                      │                        │
    │                       │  GET /auth/github    │                        │
    │                       │─────────────────────▶│                        │
    │                       │                      │  302 → github authorize│
    │                       │◀─── set oauth_state ─│   (with state param)   │
    │  redirect to github   │                      │                        │
    │──────────────────────────────────────────────────────────────────────▶│
    │                       │                      │                        │
    │  authorize            │                      │                        │
    │◀─────────────────────────────────────────────────────────────────────▶│
    │                       │                      │                        │
    │  redirect with code   │                      │                        │
    │──────────────────────────────────────────────│                        │
    │                       │                      │  exchange code         │
    │                       │                      │───────────────────────▶│
    │                       │                      │◀──── access_token ─────│
    │                       │                      │  GET /user             │
    │                       │                      │───────────────────────▶│
    │                       │                      │◀──── user info ────────│
    │                       │                      │                        │
    │                       │  302 + Set-Cookie:   │                        │
    │                       │   access_token,      │                        │
    │                       │   refresh_token,     │                        │
    │                       │   csrf_token         │                        │
    │                       │◀─────────────────────│                        │
    │  /dashboard           │                      │                        │
    │◀──────────────────────│                      │                        │
```

- `state` is generated by the backend, stored in a short-lived cookie
  (`oauth_state`, 10 min) and validated on callback.
- Session cookies are **HTTP-only** for `access_token` and `refresh_token`;
  `csrf_token` is non-HTTP-only so the SPA can read it and echo it as
  `X-CSRF-Token` on state-changing requests (double-submit cookie pattern).
- `refresh_token` cookie is path-scoped to `/auth` so it is only sent on
  refresh/logout, not on every API call.

### B. CLI flow (PKCE)

The CLI never sees the GitHub client secret. It uses PKCE:

```
   user                  CLI                    backend                 github
    │                     │                       │                       │
    │ insighta login      │                       │                       │
    │────────────────────▶│                       │                       │
    │                     │ generate state        │                       │
    │                     │ + code_verifier       │                       │
    │                     │ + code_challenge      │                       │
    │                     │ start loopback :51420 │                       │
    │                     │                       │                       │
    │                     │ open browser to       │                       │
    │                     │   github authorize    │                       │
    │                     │   (challenge, S256)   │                       │
    │ authorize in browser│                       │                       │
    │◀────────────────────┼──────────────────────────────────────────────▶│
    │                     │                       │                       │
    │ redirect to         │                       │                       │
    │ http://127.0.0.1:51420/callback?code=...&state=...                  │
    │────────────────────▶│                       │                       │
    │                     │ verify state          │                       │
    │                     │                       │                       │
    │                     │ POST /auth/cli/exchange{code, code_verifier}  │
    │                     │──────────────────────▶│                       │
    │                     │                       │ exchange + verifier   │
    │                     │                       │──────────────────────▶│
    │                     │                       │◀──── access_token ────│
    │                     │                       │ fetch user            │
    │                     │                       │──────────────────────▶│
    │                     │                       │◀──── user info ───────│
    │                     │ ◀── access + refresh ─│                       │
    │                     │                       │                       │
    │                     │ persist to            │                       │
    │                     │ ~/.insighta/credentials.json                  │
    │ Logged in as @user  │                       │                       │
    │◀────────────────────│                       │                       │
```

The CLI client app on GitHub is a **separate OAuth app** from the web portal
because the redirect URI differs (`http://127.0.0.1:<port>/callback`).

### User lifecycle

On every successful login:

- `users` row is upserted by `github_id` (mutable GitHub fields — username,
  email, avatar — synced; local fields — role, is_active — preserved).
- `last_login_at` is set to now.
- New users default to `role = analyst`.
- If `is_active = false`, login is rejected with `account_disabled` (web
  redirects to login page; CLI receives 403).

---

## Token Handling

### Token shape (JWT, HS256)

| Claim       | Access | Refresh |
|-------------|--------|---------|
| `sub`       | user id (UUID v7)     | user id |
| `role`      | `admin` / `analyst`   | —       |
| `family_id` | —                     | UUID v7 |
| `type`      | `"access"`            | `"refresh"` |
| `iat`/`exp` | yes                   | yes |

`type` is verified on decode so an access token can never be used as a refresh
token (or vice versa).

### TTLs (per spec)

| Token   | TTL     |
|---------|---------|
| Access  | 180 s (3 min) |
| Refresh | 300 s (5 min) |

### Storage

- **Access tokens** are stateless. The backend never stores them.
- **Refresh tokens** are stored as **SHA-256 hashes** in the `refresh_tokens`
  table along with `family_id`, `expires_at`, and `revoked_at`. The plaintext
  is never persisted server-side.

### Rotation + reuse detection

`POST /auth/refresh` always issues a **new pair**. The presented refresh
token is marked `revoked_at = now` immediately on success.

If a token whose `revoked_at` is already set is presented again, the backend
treats it as **token theft**: every refresh token in the same `family_id`
is revoked in one update, forcing a full re-login. This protects against an
attacker who captured an old refresh token after the rightful client already
rotated.

```
issue_session    →  family F, refresh R1   (R1 in DB, unrevoked)
client refresh   →  presents R1            (R1 → revoked, R2 issued)
client refresh   →  presents R2            (R2 → revoked, R3 issued)
attacker         →  presents R1 (stolen)   (already revoked → revoke
                                            *all* tokens with family=F;
                                            R3 invalidated, user re-logs in)
```

### Web vs CLI delivery

| Surface | Delivery |
|---------|----------|
| Web portal | HTTP-only cookies set by the backend on callback / refresh |
| CLI        | JSON body — CLI persists at `~/.insighta/credentials.json` (mode 0600) |

Both flows hit the same `rotate_refresh_token` core. `POST /auth/refresh`
accepts a refresh token from **either** the cookie or the JSON body, so the
two clients share one endpoint.

### Logout

`POST /auth/logout` is **idempotent**. It SHA-256-hashes the presented
refresh token, marks it revoked in the DB, and clears the cookies. It
succeeds even if the caller has no valid session.

---

## Role Enforcement

Two roles, enforced via a single dependency factory rather than scattered
`if`-checks.

| Role      | Permissions                                        |
|-----------|----------------------------------------------------|
| `admin`   | Read + create + delete profiles                    |
| `analyst` | Read + search only (default for new users)         |

### How it's wired

1. **Router-level auth.** Every endpoint under `/api/profiles` declares
   `dependencies=[Depends(get_current_user)]` at the router definition. There
   is no way to forget it on a new route — adding a route inherits auth.
2. **Per-endpoint role gating.** Mutating endpoints add a second dependency:

   ```python
   user: User = Depends(require_role("admin"))
   ```

   `require_role` is a factory that returns a dependency raising 403 if the
   resolved user's role is not in the allowed set.
3. **Account state.** `get_current_user` rejects disabled accounts (`is_active
   = false`) with 403 before role checks even run.

### Endpoint matrix

| Endpoint                          | Authenticated | Admin only |
|-----------------------------------|:-------------:|:----------:|
| `GET /api/profiles`               | ✓             |            |
| `GET /api/profiles/search`        | ✓             |            |
| `GET /api/profiles/{id}`          | ✓             |            |
| `GET /api/profiles/stats`         | ✓             |            |
| `GET /api/profiles/export`        | ✓             |            |
| `POST /api/profiles`              | ✓             | ✓          |
| `DELETE /api/profiles/{id}`       | ✓             | ✓          |

---

## Natural Language Parsing

`GET /api/profiles/search?q=...` accepts plain English and converts it into
the same filter set used by `GET /api/profiles`. The parser is **rule-based —
no LLM, no remote call**. It is fast, deterministic, and free.

### Pipeline

```
"young males from south africa"
        │
        ▼  lowercase + strip
"young males from south africa"
        │
        ▼  keyword scan + regex
{
  "gender":     "male",
  "min_age":    16,
  "max_age":    24,
  "country_id": "ZA"
}
        │
        ▼  reuse get_profiles() with these kwargs
paginated profile list
```

### Recognized vocabulary

| Category        | Keywords                                                    |
|-----------------|-------------------------------------------------------------|
| Gender          | `male`, `female`                                            |
| Age group       | `child`, `teenager`/`teen`, `adult`, `senior`/`elderly`/`old` |
| Age range alias | `young` → `min_age=16, max_age=24`                          |
| Numeric range   | `above N`/`over N` → `min_age=N`; `below N`/`under N` → `max_age=N` |
| Country         | full English country name (e.g. `nigeria`, `south africa`, `dr congo`) |

Multi-word country names are matched **before** single-word ones (longest
first) so "south africa" doesn't collapse into a partial match.

### Failure mode

If no keyword matches, the parser returns `None` and the endpoint responds
with HTTP 200 and:

```json
{ "status": "error", "message": "Unable to interpret query" }
```

This intentionally avoids 4xx because the request itself is well-formed.

---

## API Reference

> **All `/api/*` requests must include `X-API-Version: 1`.** Missing the
> header returns 400 with `{"status": "error", "message": "API version header required"}`.

> **All `/api/*` requests require authentication** (Bearer token from CLI, or
> cookie from web portal).

### Auth

| Method | Path                       | Description                            |
|--------|----------------------------|----------------------------------------|
| GET    | `/auth/github`             | Start the web OAuth flow               |
| GET    | `/auth/github/callback`    | OAuth redirect target (web)            |
| POST   | `/auth/cli/exchange`       | CLI PKCE exchange (`code`, `code_verifier`) |
| POST   | `/auth/refresh`            | Rotate refresh token (cookie or body)  |
| POST   | `/auth/logout`             | Revoke refresh token + clear cookies   |
| GET    | `/auth/me`                 | Current user                           |

### Profiles

| Method | Path                              | Role        | Notes                          |
|--------|-----------------------------------|-------------|--------------------------------|
| GET    | `/api/profiles`                   | any         | filter / sort / paginate       |
| GET    | `/api/profiles/search?q=...`      | any         | NL → filters                   |
| GET    | `/api/profiles/stats`             | any         | aggregates                     |
| GET    | `/api/profiles/export?format=csv` | any         | streaming CSV                  |
| GET    | `/api/profiles/{id}`              | any         | single profile                 |
| POST   | `/api/profiles`                   | **admin**   | enriches via Genderize/Agify/Nationalize |
| DELETE | `/api/profiles/{id}`              | **admin**   | hard delete                    |

### Pagination envelope

```json
{
  "status": "success",
  "page": 1,
  "limit": 10,
  "total": 2026,
  "total_pages": 203,
  "links": {
    "self": "/api/profiles?page=1&limit=10",
    "next": "/api/profiles?page=2&limit=10",
    "prev": null
  },
  "data": [ ... ]
}
```

`next`/`prev` are `null` at the boundaries. All current query parameters
(filters, sort, q) are preserved in the link URLs.

### List filters

| Param                      | Type   | Notes                                         |
|----------------------------|--------|-----------------------------------------------|
| `gender`                   | string | `male` / `female`                             |
| `age_group`                | string | `child` / `teenager` / `adult` / `senior`     |
| `country_id`               | string | ISO-3166-1 alpha-2, e.g. `NG`                 |
| `min_age`, `max_age`       | int    | inclusive                                     |
| `min_gender_probability`   | float  | 0–1                                           |
| `min_country_probability`  | float  | 0–1                                           |
| `sort_by`                  | string | `age` / `created_at` / `gender_probability`   |
| `order`                    | string | `asc` / `desc` (default `asc`)                |
| `page`                     | int    | default 1                                     |
| `limit`                    | int    | default 10, max 50                            |

### CSV export

```
GET /api/profiles/export?format=csv&gender=male&country_id=NG
```

Response:

```
HTTP/1.1 200 OK
Content-Type: text/csv
Content-Disposition: attachment; filename="profiles_20260430T101500Z.csv"

id,name,gender,gender_probability,age,age_group,country_id,country_name,country_probability,created_at
...
```

Column order is fixed per spec. Streamed row-by-row (no full-result
buffering) to scale beyond memory.

### Error envelope

Every error response, including 4xx and 5xx, is shaped:

```json
{ "status": "error", "message": "..." }
```

| Status | Meaning                                |
|--------|----------------------------------------|
| 400    | Missing/invalid query param or header  |
| 401    | Missing or invalid token               |
| 403    | Wrong role / disabled account / CSRF   |
| 404    | Profile not found                      |
| 422    | Invalid parameter type                 |
| 429    | Rate limit exceeded                    |
| 502    | Upstream enrichment API failed         |
| 500    | Unhandled error                        |

---

## CLI Usage

The CLI lives in a separate repository (`insighta-cli`). It speaks to this
backend over the same `/auth/*` and `/api/*` surface — no special endpoints.

```bash
insighta login                                       # PKCE OAuth flow
insighta logout
insighta whoami

insighta profiles list
insighta profiles list --gender male --country NG
insighta profiles list --min-age 25 --max-age 40
insighta profiles list --sort-by age --order desc --page 2 --limit 20

insighta profiles get <id>
insighta profiles search "young males from nigeria"
insighta profiles create --name "Harriet Tubman"     # admin only
insighta profiles export --format csv --gender male  # writes CSV to cwd
```

Credentials are persisted at `~/.insighta/credentials.json`. The CLI
refreshes the access token automatically when it expires; if the refresh
token is also expired or rejected, it prompts for re-login.

---

## Local Setup

### 1. Clone and install

```bash
git clone <backend-repo-url>
cd insighta-labs/backend
uv sync
```

### 2. Configure

```bash
cp .env.example .env
# Fill in DATABASE_URL, GitHub OAuth client IDs/secrets, JWT_SECRET, etc.
```

### 3. Run migrations

```bash
uv run alembic upgrade head
```

### 4. (Optional) Seed Stage 2 profile data

```bash
uv run python seed.py
```

Idempotent — re-running skips existing rows via `ON CONFLICT DO NOTHING`.

### 5. Start the server

```bash
uv run uvicorn app.main:app --reload
```

API at `http://localhost:8000`. Health: `GET /health`.

---

## Configuration

All configuration is via environment variables. See [`.env.example`](.env.example)
for the canonical list. Highlights:

| Variable                         | Purpose                                            |
|----------------------------------|----------------------------------------------------|
| `DATABASE_URL`                   | `postgresql+asyncpg://...`                         |
| `GITHUB_WEB_CLIENT_ID/SECRET`    | OAuth app for the web portal                       |
| `GITHUB_CLI_CLIENT_ID/SECRET`    | Separate OAuth app for the CLI (PKCE)              |
| `GITHUB_CLI_CALLBACK_PORT`       | Loopback port the CLI listens on (default 51420)   |
| `JWT_SECRET`                     | HS256 signing secret — rotate if leaked            |
| `ACCESS_TOKEN_TTL_SECONDS`       | Access TTL (180 per spec)                          |
| `REFRESH_TOKEN_TTL_SECONDS`      | Refresh TTL (300 per spec)                         |
| `BACKEND_PUBLIC_URL`             | Where the backend is reachable from clients        |
| `WEB_APP_ORIGIN`                 | Web portal origin — used for CORS + post-login redirect |
| `COOKIE_SECURE`                  | `true` in prod (HTTPS), `false` for local dev       |
| `COOKIE_SAMESITE`                | `lax` for same-site, `none` for cross-site (with `secure=true`) |
| `COOKIE_DOMAIN`                  | Optional explicit cookie domain                    |

CORS is restricted to `WEB_APP_ORIGIN` with `allow_credentials=True` so the
web portal's HTTP-only cookies cross the origin boundary. The CLI uses Bearer
tokens and is unaffected by CORS.

---

## Database Schema

### `profiles`

| Column                | Type         | Notes                                |
|-----------------------|--------------|--------------------------------------|
| id                    | UUID v7      | PK                                   |
| name                  | VARCHAR      | Unique, indexed                      |
| gender                | VARCHAR      | `male` / `female`                    |
| gender_probability    | FLOAT        | 0–1                                  |
| age                   | INT          |                                      |
| age_group             | VARCHAR      | `child` / `teenager` / `adult` / `senior` (indexed) |
| country_id            | VARCHAR(20)  | ISO 3166-1 alpha-2 (indexed)         |
| country_name          | VARCHAR      |                                      |
| country_probability   | FLOAT        | 0–1                                  |
| created_at            | TIMESTAMPTZ  | server-default `now()`               |
| updated_at            | TIMESTAMPTZ  | auto-updated                         |

### `users`

| Column           | Type         | Notes                                          |
|------------------|--------------|------------------------------------------------|
| id               | UUID v7      | PK                                             |
| github_id        | VARCHAR(32)  | Unique                                         |
| username         | VARCHAR(64)  | Indexed                                        |
| email            | VARCHAR(255) | Nullable                                       |
| avatar_url       | VARCHAR      | Nullable                                       |
| role             | VARCHAR(16)  | CHECK in (`admin`, `analyst`); default `analyst` |
| is_active        | BOOLEAN      | Default `true`; if false → 403 everywhere      |
| last_login_at    | TIMESTAMPTZ  | Updated on every successful login              |
| created_at       | TIMESTAMPTZ  |                                                |

### `refresh_tokens`

| Column      | Type         | Notes                                         |
|-------------|--------------|-----------------------------------------------|
| id          | UUID v7      | PK                                            |
| user_id     | UUID         | FK → `users.id` (`ON DELETE CASCADE`)         |
| token_hash  | VARCHAR(64)  | SHA-256 hex of the raw token, unique          |
| family_id   | UUID         | Rotation family — reuse triggers family-wide revoke |
| expires_at  | TIMESTAMPTZ  |                                               |
| revoked_at  | TIMESTAMPTZ  | Nullable; set on rotation, logout, or theft   |
| created_at  | TIMESTAMPTZ  |                                               |

---

## Rate Limiting & Logging

### Rate limits

| Scope                  | Limit             | Key             |
|------------------------|-------------------|-----------------|
| `/auth/*`              | 10 / minute       | client IP       |
| `/api/*` (everything)  | 60 / minute       | user id (or IP if unauthenticated) |

429 responses include a `Retry-After` header where available.

### Request logging

Every request emits one structured line:

```
2026-04-30 10:15:00 - app.request - INFO - GET /api/profiles status=200 duration=12.3ms req_id=...
```

Fields: HTTP method, path, status code, response time, request ID. The
request ID is also stamped on the response as `X-Request-ID` for easy
client-side correlation.

---

## Testing & CI

```bash
uv run pytest -q
uv run ruff check .
```

The suite uses an in-memory SQLite via `aiosqlite`, so it runs without a
Postgres dependency. Coverage spans:

- API versioning (header presence + value)
- Authentication (token decode, expiry, type mismatch)
- Role enforcement (analyst blocked from admin endpoints)
- Pagination shape (envelope fields, link generation)
- CSV export (columns, ordering, filters)
- Profile filters / sort / search

GitHub Actions (`.github/workflows/ci.yml`) runs lint + tests on every PR
and push to `main`.

---

## Deployment

The repo ships a `Procfile`:

```
web: uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

For production deployment:

1. Provide `DATABASE_URL` pointing at a managed Postgres (e.g. Neon, RDS).
2. Set `COOKIE_SECURE=true` and `COOKIE_SAMESITE=lax` (or `none` if the web
   portal is on a different registrable domain — then it must also be
   `secure=true`).
3. Set `BACKEND_PUBLIC_URL` to the deployed backend URL and `WEB_APP_ORIGIN`
   to the deployed web portal URL — CORS, cookies, and OAuth redirects all
   read from these.
4. Register two GitHub OAuth apps (web + CLI) and supply both pairs of
   credentials.
5. Run `alembic upgrade head` on first boot.

---

## Grader Hooks

The automated submission grader cannot drive a real GitHub OAuth flow, so
the backend exposes two seeded test users it can reach.

### Admin: `code=test_code` shortcut

`GET /auth/github/callback?code=test_code` (and `POST /auth/cli/exchange`
with body `{"code": "test_code", "code_verifier": "..."}`) bypasses the
GitHub round-trip and returns a fresh admin session as JSON:

```json
{
  "status": "success",
  "access_token": "...",
  "refresh_token": "...",
  "user": { "id": "...", "username": "grader-admin", "role": "admin" }
}
```

The user is upserted on first call and reused thereafter. State / cookie
checks are skipped because the grader cannot set the `oauth_state` cookie.
Leave the "Admin Test Token" and "Refresh Test Token" fields blank on the
submission form — the grader extracts both automatically from this response.

### Analyst: long-lived token

For analyst-role tests, mint a 24-hour token once at submission time:

```bash
uv run python scripts/mint_grader_analyst.py
```

This upserts a `grader-analyst` user (role=analyst) and prints a JWT with
a 24h expiry — well past the configured 180s access TTL. Paste the output
into the "Analyst Test Token" field.

### Why two flows

Access tokens default to 3 minutes per Stage 3 spec. The grader's evaluation
run can outlive that. The `test_code` shortcut sidesteps this for admin
because the grader can re-trigger it any time. For analyst, since the spec
only asks for a single bearer token (no refresh slot), we mint one with a
longer custom TTL specifically for evaluation.

The grader users live alongside real users in the same `users` table; they
have non-GitHub `github_id` values (`grader-admin`, `grader-analyst`) so
they can never collide with a real GitHub login.

---

## Author

**Nadduli Daniel** — naddulidaniel94@gmail.com
[GitHub](https://github.com/naddulidaniel) · [LinkedIn](https://linkedin.com/in/nadduli-daniel)
