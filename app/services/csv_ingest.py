"""CSV bulk-ingest service.

Streams a CSV upload through validation + batched COPY into Postgres.
Designed for Stage 4b's requirements:

  - Never load the whole file (csv.DictReader iterates lazily over the
    underlying SpooledTemporaryFile; one row in memory at a time, plus
    the current chunk of CHUNK_SIZE rows).
  - Insert in bulk via COPY ... FROM STDIN (one DB round-trip per chunk
    of 5,000 rows, not per row).
  - Skip bad rows without aborting (counted, attributed in the summary).
  - Idempotent on `name` via INSERT ... ON CONFLICT DO NOTHING.
  - Partial-failure safe: each chunk commits in its own transaction.
    If a later chunk fails, earlier chunks stay inserted.

The CSV's required columns are name, gender, age, country_id. Optional
columns (age_group, country_name, gender_probability, country_probability)
are auto-filled when absent.
"""

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import IO

import asyncpg
import pycountry
import uuid_extensions

from ..config import get_settings
from . import query_cache

logger = logging.getLogger(__name__)

# 5,000 rows per COPY batch. Large enough that round-trip overhead is
# amortized; small enough that one failed chunk wastes little progress.
CHUNK_SIZE = 5_000

ALLOWED_GENDERS = {"male", "female"}
MIN_AGE = 0
MAX_AGE = 120

# Minimum fields a row must carry. Everything else is either optional
# with auto-fill or supplied by the database (id, created_at, updated_at).
REQUIRED_FIELDS = ("name", "gender", "age", "country_id")

# COPY column order. MUST match the tuple yielded by _build_record().
_COPY_COLUMNS = [
    "id", "created_at", "updated_at",
    "name", "gender", "gender_probability",
    "age", "age_group", "country_id", "country_name",
    "country_probability",
]


@dataclass
class IngestSummary:
    """Counters reported back to the API caller after an upload."""

    total_rows: int = 0
    inserted: int = 0
    skipped: int = 0
    reasons: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def to_dict(self) -> dict:
        return {
            "total_rows": self.total_rows,
            "inserted": self.inserted,
            "skipped": self.skipped,
            "reasons": dict(self.reasons),
        }


def _classify_age_group(age: int) -> str:
    if age <= 12:
        return "child"
    if age <= 19:
        return "teenager"
    if age <= 59:
        return "adult"
    return "senior"


def _country_name(country_id: str) -> str:
    """Resolve ISO-3166 alpha-2 to a country name; fall back to the code."""
    record = pycountry.countries.get(alpha_2=country_id.upper())
    return record.name if record else country_id


def _validate_row(row: dict) -> tuple[bool, str | None]:
    """Return (is_valid, skip_reason_if_invalid).

    Reasons exposed in the response: missing_fields, invalid_gender,
    invalid_age, malformed_row.
    """
    # csv.DictReader produces None for missing trailing values when the
    # row is shorter than the header — treat those as malformed.
    if any(v is None for v in row.values()):
        return False, "malformed_row"

    # Required-field presence (non-empty after stripping whitespace)
    for name in REQUIRED_FIELDS:
        value = row.get(name)
        if value is None or not str(value).strip():
            return False, "missing_fields"

    if row["gender"].strip().lower() not in ALLOWED_GENDERS:
        return False, "invalid_gender"

    try:
        age = int(row["age"])
    except (ValueError, TypeError):
        return False, "invalid_age"
    if age < MIN_AGE or age > MAX_AGE:
        return False, "invalid_age"

    return True, None


def _build_record(row: dict, now: datetime) -> tuple:
    """Build a Postgres COPY tuple from a validated row.

    Auto-fills optional fields:
      - age_group: derived from age if absent
      - country_name: pycountry lookup if absent
      - {gender,country}_probability: default 1.0 if absent or unparseable

    The yielded tuple's column order MUST match _COPY_COLUMNS.
    """
    age = int(row["age"])
    age_group = (row.get("age_group") or "").strip().lower() or _classify_age_group(age)
    country_id = row["country_id"].strip().upper()
    country_name = (row.get("country_name") or "").strip() or _country_name(country_id)

    def _to_float(raw, default: float) -> float:
        try:
            return float(raw) if raw not in (None, "") else default
        except (ValueError, TypeError):
            return default

    return (
        uuid_extensions.uuid7(),                  # id
        now,                                      # created_at
        now,                                      # updated_at
        row["name"].strip(),                      # name
        row["gender"].strip().lower(),            # gender
        _to_float(row.get("gender_probability"), 1.0),
        age,                                      # age
        age_group,                                # age_group
        country_id,                               # country_id
        country_name,                             # country_name
        _to_float(row.get("country_probability"), 1.0),
    )


async def _flush_chunk(
    conn: asyncpg.Connection,
    batch: list[tuple],
    summary: IngestSummary,
) -> None:
    """COPY the batch into a TEMP staging table, then merge with conflict skip.

    Each chunk runs in its own transaction so a later failure doesn't
    roll back earlier successful chunks (per spec: "rows already
    inserted must remain").
    """
    if not batch:
        return

    async with conn.transaction():
        # Defensive DROP (Neon's pooled session may persist a leftover
        # temp table from a prior run). ON COMMIT DROP cleans up after
        # each chunk's commit.
        await conn.execute("DROP TABLE IF EXISTS staging_profiles")
        await conn.execute(
            "CREATE TEMP TABLE staging_profiles (LIKE profiles) ON COMMIT DROP"
        )
        await conn.copy_records_to_table(
            "staging_profiles", records=batch, columns=_COPY_COLUMNS
        )
        result = await conn.execute("""
            INSERT INTO profiles
            SELECT * FROM staging_profiles
            ON CONFLICT (name) DO NOTHING
        """)

    # asyncpg returns "INSERT 0 N" — the last token is the row count.
    inserted_n = int(result.split()[-1]) if result else 0
    duplicates_n = len(batch) - inserted_n

    summary.inserted += inserted_n
    if duplicates_n:
        summary.skipped += duplicates_n
        summary.reasons["duplicate_name"] += duplicates_n


async def ingest_csv_stream(file_stream: IO) -> IngestSummary:
    """Stream a CSV through validation + batched COPY. Returns the summary.

    `file_stream` must yield text lines. UploadFile.file wrapped in
    TextIOWrapper satisfies this contract; so does an open()'d local
    file in text mode.

    Raises ValueError on missing/invalid header — caller should map that
    to HTTP 400.
    """
    summary = IngestSummary()

    settings = get_settings()
    raw_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    conn = await asyncpg.connect(raw_url, ssl="require")

    try:
        reader = csv.DictReader(file_stream)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        missing_required = set(REQUIRED_FIELDS) - set(reader.fieldnames)
        if missing_required:
            raise ValueError(
                f"CSV missing required column(s): {sorted(missing_required)}"
            )

        batch: list[tuple] = []
        now = datetime.now(timezone.utc)

        for row in reader:
            summary.total_rows += 1

            valid, reason = _validate_row(row)
            if not valid:
                summary.skipped += 1
                summary.reasons[reason] += 1
                continue

            try:
                batch.append(_build_record(row, now))
            except Exception as e:
                logger.warning(f"_build_record failed for row: {e}")
                summary.skipped += 1
                summary.reasons["build_error"] += 1
                continue

            if len(batch) >= CHUNK_SIZE:
                await _flush_chunk(conn, batch, summary)
                batch.clear()

        # Flush the trailing partial batch
        if batch:
            await _flush_chunk(conn, batch, summary)
    finally:
        await conn.close()

    # Cached query results may now be stale; drop them so analysts see
    # the new data on the next read.
    await query_cache.invalidate_all()

    return summary
