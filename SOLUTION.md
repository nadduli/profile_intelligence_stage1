# Insighta Labs+ Stage 4b — SOLUTION

Implementation notes for the three Stage 4b deliverables: query
performance, query normalization, and CSV ingestion. This document
covers the approach, the decisions behind it, the measured impact, and
the limitations I left in honestly.

## Contents

- [1. Setup for honest measurement](#1-setup-for-honest-measurement)
- [2. Query performance](#2-query-performance)
- [3. Query normalization](#3-query-normalization)
- [4. CSV ingestion](#4-csv-ingestion)
- [5. Trade-offs and limitations](#5-trade-offs-and-limitations)

---

## 1. Setup for honest measurement

Before any optimization, I built the rig that proves the claims:

| File | Purpose |
|---|---|
| `scripts/generate_csv.py` | Synthetic CSV producer (configurable row count, realistic gender/age/country distribution) |
| `scripts/load_csv.py` | Streaming `COPY` loader → temp staging → `INSERT ... ON CONFLICT DO NOTHING`. Same pattern the production upload endpoint uses. |
| `scripts/benchmark.py` | Runs a fixed query mix N times, reports P50/P95/P99 |

I seeded **~103,000 profiles** (1k smoke-test + 100k synthetic) into the
existing Neon database. The original 2,026 seed rows stayed untouched —
synthetic rows have a `Test#######` name suffix so they're easily
distinguished.

The benchmark sends six representative queries, 50 iterations each,
sequential (we're measuring per-query latency, not throughput):

```
list:no-filter        — bare /api/profiles?limit=10
list:gender           — single-predicate filter
list:gender+country   — multi-predicate
list:heavy-filter     — gender + country + age range
search:nl             — natural-language query through the parser
stats                 — aggregate /api/profiles/stats
```

For local benchmarking I added two env-driven dev toggles
(`RATE_LIMIT_ENABLED=false`, `ACCESS_TOKEN_TTL_SECONDS=3600`) so 60/min
rate limits and 3-minute token expiry don't interrupt a measurement
run. Both default to spec values (`True`, `180`) so production stays
strict — the toggles are never set on Railway.

---

## 2. Query performance

### 2a. Composite index on the dominant filter pattern

`alembic/versions/5457380f5462_add_profile_query_indexes.py` adds two
indexes:

```sql
CREATE INDEX ix_profiles_country_gender_age ON profiles (country_id, gender, age);
CREATE INDEX ix_profiles_created_at_desc    ON profiles (created_at DESC);
```

**Order is deliberate.** `country_id` first because it's highest-cardinality
and almost every filtered query has it. `gender` next, `age` last for
range conditions. The created_at DESC index covers the API's default
sort on unfiltered list queries.

Existing single-column indexes on `country_id` and `age_group` are kept —
storage is cheap and they cover queries that filter on only one of those
columns.

### 2b. In-memory TTL caches

Three caches, all behind the same thin `get/set/invalidate/invalidate_all`
abstraction in `app/services/query_cache.py` so the backing store can be
swapped to Redis later without touching call sites:

| Wraps | TTL | Why this TTL |
|---|---|---|
| `get_profiles()` (filter+paginate) | 60s | Long enough for analyst pagination / refresh-clicks to hit cache. Explicit invalidation on writes is the dominant freshness mechanism. |
| `get_stats()` (aggregations) | 60s | Same. Aggregates change only when profiles are added/deleted. |
| `get_user_by_id()` (auth path) | 30s | Shorter so disabled-account changes propagate fast even without explicit invalidation. |

The user-id cache is **the load-bearing one**. Every authenticated
request goes through `get_current_user`, which calls `get_user_by_id`.
Without that cache, even cache-hit profile queries paid one DB
round-trip per request for the user lookup — that was the dominant cost.

### 2c. Filter normalization for cache keys

`app/services/normalize.py` canonicalizes a filter dict before hashing:
known fields only (so unexpected query params don't fragment the cache),
type coercion (`int`/`float`), case normalization (country codes
uppercased, everything else lowercased), `None`/empty stripped, JSON
serialized with `sort_keys=True`. SHA-256, first 16 hex chars as the
key.

Result: `?gender=MALE&country_id=ng&page=` and `?country_id=NG&gender=male`
collapse to the same cache entry.

### 2d. Cache invalidation on writes

`POST /api/profiles` and `DELETE /api/profiles/{id}` call
`query_cache.invalidate_all()` after the DB mutation. Same on the new
`POST /api/profiles/upload`. The all-flush is intentional: figuring
out which cache entries a new row affects is more complexity than it
buys, and the cache repopulates on the next read. In-process flush is
sub-millisecond.

### 2e. Measured impact

Tested locally against Neon (the same setup the live app uses), 50
iterations per query, sequential. The dataset is 102,979 profiles.

| Query | Stage 3 baseline P50 | After indexes P50 | **After cache P50** | Speedup vs baseline |
|---|---|---|---|---|
| list:no-filter | 1955 ms | 2152 ms | **2.0 ms** | **~1000×** |
| list:gender | 1748 ms | 2150 ms | **1.7 ms** | **~1030×** |
| list:gender+country | 1968 ms | 2152 ms | **1.8 ms** | **~1090×** |
| list:heavy-filter | 1854 ms | 2186 ms | **1.8 ms** | **~1030×** |
| search:nl | 1885 ms | 2152 ms | **2.7 ms** | **~700×** |
| stats | 2530 ms | 2765 ms | **2.3 ms** | **~1100×** |

P95 on cached responses sits between **3 ms and 6 ms** for every query.
Stage 4b's "low hundreds of ms" target is met by ~50× margin on cache hits.

### 2f. Why the index column is mostly flat

The "after indexes only" column shows roughly the same numbers as the
baseline — a finding that's worth documenting honestly. I confirmed it
with `EXPLAIN ANALYZE`:

```
Bitmap Index Scan on ix_profiles_country_gender_age
Execution Time: 3.314 ms
Planning Time: 0.141 ms
```

Postgres execution is **3 ms**. The remaining ~2 seconds is
**network round-trip** between my machine (and Railway, when deployed)
and Neon's region. No schema change can shrink that — it's
infrastructure latency, not query work.

This made the cache the actual hero of Stage 4b. The indexes still
matter: they keep query execution from degrading as the dataset grows,
which a benchmark at 100K rows can't show but matters at 10M+. They are
necessary but not sufficient.

### 2g. Connection pooling

`app/database.py` already had `pool_pre_ping=True` and `pool_recycle=300`.
For the current scale (single Railway process, hundreds of qpm) the
default async pool size is fine. I left it untuned — there was no
contention to fix in benchmarks. If the system grew to multiple
instances or heavier concurrent writes, I'd revisit using
`pool_size`/`max_overflow` against Neon's connection cap.

---

## 3. Query normalization

### 3a. Two layers of normalization

The spec example —

> "Nigerian females between ages 20 and 45" and
> "Women aged 20-45 living in Nigeria"

— must produce the same cache key. That requires correctness at two
distinct layers:

1. **The parser** must turn both phrasings into the *same* filter dict.
   "Women" must equal "females"; "between ages 20 and 45" must equal
   "20-45".
2. **The cache-key derivation** must turn equivalent dicts into the
   same hash regardless of key order, casing, or extraneous keys.

If either layer leaks, equivalent queries hit different cache entries
and we pay redundant DB round-trips for nothing.

### 3b. Parser changes (`app/services/query_parser.py`)

Two additions to the existing rule-based parser:

- **Gender synonyms** with explicit `\b` word boundaries:
  - `female` ← `female(s)`, `woman`/`women`, `lady`/`ladies`, `girl(s)`
  - `male` ← `male(s)`, `man`/`men`, `gentleman`/`gentlemen`, `boy(s)`,
    `guy(s)`
  - Word boundaries prevent accidental matches like `men` inside
    `amenable`.

- **Age range patterns**, checked in priority order:
  1. `between [ages] X and|to|- Y` → `min_age=X, max_age=Y`
  2. `aged?|ages? X and|to|- Y`
  3. `(aged?\s+)?X-Y` (standalone digit range, with `\d` boundaries so
     it doesn't grab inside larger numbers)

Range patterns take precedence over the existing single-bound
(`above X` / `below Y`) and over coarse age-group keywords, because a
numeric range is the most specific intent.

Both spec phrasings now produce the same filter dict:

```python
{"gender": "female", "country_id": "NG", "min_age": 20, "max_age": 45}
```

### 3c. Cache-key derivation (`app/services/normalize.py`)

`canonicalize(filters)` then `cache_key(filters)`:

- `_KNOWN_FIELDS` allowlist — anything else is dropped, so the cache
  isn't fragmented by stray params (e.g. tracking IDs).
- Per-field type coercion: `int`, `float`, lowercase strings,
  uppercase country codes (matches DB contract).
- `None`/empty stripped.
- `json.dumps(..., sort_keys=True, separators=(",", ":"))` for
  deterministic serialization.
- SHA-256, first 16 hex chars, prefixed `profiles:` for namespacing.

### 3d. Determinism + correctness invariants

`tests/test_query_normalization.py` locks in the spec invariants:

- Both spec phrasings produce the same filter dict.
- Both share the same `cache_key`.
- All five range phrasings (between / between ages / aged X to Y /
  aged X-Y / ages X and Y) produce identical keys.
- Word boundaries prevent synonym-substring false positives.
- `canonicalize` drops unknown fields and normalizes case.

Eight tests, all passing. No AI/LLM in the path — the parser is purely
regex + lookup tables.

---

## 4. CSV ingestion

### 4a. Endpoint and pipeline

`POST /api/profiles/upload`, admin-only, multipart/form-data.
Implementation in `app/services/csv_ingest.py`:

```
UploadFile (Spooled) → TextIOWrapper → csv.DictReader
                                        ↓ row by row (lazy)
                              _validate_row → reason or pass
                                        ↓
                              _build_record → COPY tuple
                                        ↓ batched at 5,000 rows
                              _flush_chunk:
                                BEGIN
                                  CREATE TEMP TABLE staging (LIKE profiles)
                                  COPY into staging from STDIN
                                  INSERT INTO profiles
                                    SELECT * FROM staging
                                    ON CONFLICT (name) DO NOTHING
                                COMMIT
                                        ↓
                              accumulate IngestSummary
                                        ↓
                              query_cache.invalidate_all()
                                        ↓
                              return {status, total_rows, inserted, skipped, reasons}
```

### 4b. How each spec requirement is satisfied

| Spec requirement | How |
|---|---|
| Up to 500K rows / file | Streaming throughout — only one row + the current 5,000-row chunk in memory at any time. Tested with 1K + 100K. |
| Comma delimiter | `csv.DictReader` default. |
| Don't insert one-by-one | One COPY per chunk of 5,000 rows. Postgres-side bulk ingest, ~50–100× faster than per-row INSERTs. |
| Don't load entire file | `csv.DictReader` reads from the SpooledTemporaryFile lazily; we hold one row at a time. |
| Streaming / chunked | See above — chunk size constant, `_flush_chunk` per chunk. |
| Don't block queries | Each chunk awaits its DB calls, so the event loop yields between chunks. Concurrent reads stay responsive (verified locally — running the upload while running the benchmark produced no read-side timeouts). |
| Concurrent uploads | Separate `asyncpg.connect(...)` per upload call — no shared state. SQLAlchemy session pool stays free for query traffic. |
| Skip rows: missing required fields | `_validate_row` flags `missing_fields` if `name`, `gender`, `age`, or `country_id` is empty. |
| Skip rows: invalid values | `invalid_gender` (vocabulary check), `invalid_age` (type + range 0–120). |
| Skip rows: duplicate name | `INSERT ... ON CONFLICT (name) DO NOTHING`. The DB-level conflict count is `len(batch) - inserted`, attributed to `duplicate_name`. |
| Skip rows: malformed | `csv.DictReader` returns `None` for missing trailing values when a row is shorter than the header — caught as `malformed_row`. |
| Single bad row never aborts | Validation skips are counted, not raised. Build errors are caught per row. Only header errors abort (mapped to HTTP 400). |
| No global rollback on partial failure | Each chunk runs in its own transaction. If chunk N fails, chunks 1..N-1 stay committed. Cache is still invalidated to reflect the partial insert. |
| Response shape | Matches spec exactly: `{status, total_rows, inserted, skipped, reasons{...}}`. |

### 4c. Why staging table + ON CONFLICT

The unique constraint on `name` would cause a single duplicate to abort
the entire COPY batch (all-or-nothing). Loading into a constraint-free
TEMP staging table first, then merging with `ON CONFLICT DO NOTHING`,
gives us:

- Per-chunk COPY never aborts on a duplicate
- Duplicate count comes back as `len(batch) - inserted` (no extra
  pre-check round-trip)
- Same idempotency rule as `POST /api/profiles` — re-running the upload
  is safe

The TEMP table uses `ON COMMIT DROP` plus a defensive
`DROP TABLE IF EXISTS`. The defensive drop is for Neon specifically:
their connection pooler keeps the underlying session alive across
script invocations, so a session-scoped temp table can leak between
runs and cause `DuplicateTableError`. I learned this the hard way
writing `scripts/load_csv.py` and applied the same fix here.

### 4d. Live verification

```bash
# Idempotent re-upload of an already-loaded 1K CSV — every row is a duplicate
$ curl -X POST .../api/profiles/upload -F "file=@sample_data/test.csv" ...
{"status":"success","total_rows":1000,"inserted":0,"skipped":1000,
 "reasons":{"duplicate_name":1000}}

# Mixed-validity dirty CSV — 1 valid, 3 with different defects
$ curl -X POST .../api/profiles/upload -F "file=@/tmp/dirty.csv" ...
{"status":"success","total_rows":4,"inserted":1,"skipped":3,
 "reasons":{"missing_fields":1,"invalid_age":1,"invalid_gender":1}}
```

Both end-to-end cases match expectations.

---

## 5. Trade-offs and limitations

### 5.1 In-memory cache, not Redis

The Stage 4a design doc names Upstash Redis as the cache layer. For
Stage 4b's stated constraints — "limited compute resources",
"no horizontal scaling", "single-region" — an in-process `TTLCache` is
the right fit:

- No infrastructure to provision or pay for at this scale
- No network hop on cache hits (sub-microsecond reads vs. ~1–5ms for
  Redis)
- Identical surface area through the `query_cache` module's
  get/set/invalidate functions, so swapping to Redis later is a
  one-file change

The day Insighta scales to multiple FastAPI instances, the in-memory
cache stops being a shared truth (each process has its own copy). At
that point Redis becomes correct, not just nicer. Until then it would
be infrastructure for a constraint we don't have.

### 5.2 Cache freshness is TTL + flush-on-write

Cache entries live up to 60 seconds before TTL expiry. Mutations
(create / delete / upload) flush the entire query cache, so writes
propagate immediately. Between writes, an analyst running the same
query twice within the TTL window sees the same result — not a
real-time view. For a batch-ingested demographic platform this is fine
and matches what the design doc commits to.

If real-time freshness becomes a requirement (e.g. continuous ingestion
instead of batch), TTL-based invalidation needs to be replaced with
event-driven per-record invalidation, and the scope of `invalidate_all`
becomes too coarse.

### 5.3 No global rollback on upload partial failure

By spec ("rows already inserted must remain") each chunk commits in its
own transaction. If chunk 8 of 10 fails, chunks 1–7 stay inserted and
the summary reports what was processed up to the failure. This is the
right call for a 500K-row upload — the alternative (single transaction
spanning the whole file) would multiply lock-hold time and starve
concurrent reads.

The cost: there's no "undo" path. If a faulty CSV is uploaded by
accident, cleanup is manual (DELETE WHERE name LIKE ... or similar).
For now I rely on the validation rules to make accidental garbage
unlikely; a follow-on could expose an admin "delete by name pattern"
endpoint.

### 5.4 Network latency dominates uncached responses

`EXPLAIN ANALYZE` shows the query mix executes in 3–10 ms inside
Postgres. The remaining ~1.5–2 seconds per uncached request is round-trip
overhead between the FastAPI process and Neon. Adding indexes, tuning
the pool, or rewriting queries can't shrink that — it's infrastructure
distance.

The cache makes this a non-issue for repeat queries (microseconds, no
DB at all). Cold queries still pay the round-trip. Mitigations would
be:

- Co-locate the backend and DB region (the cleanest fix)
- Read replica closer to compute (Stage 4a design doc)
- Application-level prefetch / warm-up (overkill at this scale)

### 5.5 Parser still rule-based

The query parser handles a fixed vocabulary plus the synonym/range
additions in Phase 2d. It does not understand:

- Compound geography (e.g. "East Africa" → multiple country codes)
- Multi-word unfamiliar phrasings ("middle-aged" → bounded range)
- Misspellings or typos

This was deliberate at Stage 1 and remains deliberate now — the spec
explicitly forbids LLMs and asks for a deterministic approach. The
follow-on path (per the design doc's §6.2) is a semantic embedding
layer that maps free text to filter intent, slotting in front of the
existing structured filters.

### 5.6 Single-region

The whole platform sits in one cloud region (Railway + Neon, both
accessible from one geography). A regional outage takes everything
down. For internal-team usage this is acceptable cost; if Insighta
served external customers with uptime SLAs, multi-region replication
would be required and would introduce its own consistency trade-offs.

### 5.7 What I'd revisit at 10× the load

- **Per-instance in-memory cache becomes a liability** with multiple
  FastAPI processes — each gets a private copy, hit rate drops by ~N.
  Move to Redis (the design doc's plan).
- **Sequential upload chunks** are simple but limit throughput; with a
  500K-row file at 5K per chunk that's 100 round-trips. Could be
  parallelized with a small connection pool dedicated to ingestion.
- **`invalidate_all()` on every write** is fine when writes are rare
  (batch ingestion). Under continuous-write load it would defeat the
  cache; per-key invalidation becomes worth the complexity.
- **Connection-level statement timeouts** (none currently) would prevent
  a single runaway query from hogging a pool slot.

---

*Author: Nadduli Daniel · Insighta Labs+ Stage 4b · 2026-05-05*
