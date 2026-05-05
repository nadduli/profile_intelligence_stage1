"""Stream-load a CSV of profile data into Postgres via COPY ... FROM STDIN.

Idempotent: COPYs into a TEMP staging table, then INSERTs into the real
table with ON CONFLICT (name) DO NOTHING. Re-runs are safe — duplicates
are silently skipped, originals stay put. Same pattern the production
upload endpoint uses in Phase 3.

Usage:
    uv run python scripts/load_csv.py sample_data/profiles_100k.csv
"""

import argparse
import asyncio
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow `python scripts/load_csv.py ...` from the repo root by prepending the
# backend root to sys.path before importing from `app.*`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg  # noqa: E402
import uuid_extensions  # noqa: E402

from app.config import get_settings  # noqa: E402


def stream_rows(csv_path: Path):
    """Yield row tuples in column order matching the COPY call.

    csv.DictReader pulls one row at a time off disk, so memory stays
    bounded no matter how big the file is. asyncpg pulls from this
    generator as fast as Postgres can drain its COPY buffer.
    """
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            now = datetime.now(timezone.utc)
            yield (
                uuid_extensions.uuid7(),                # id
                now,                                    # created_at
                now,                                    # updated_at
                row["name"],
                row["gender"],
                float(row["gender_probability"]),
                int(row["age"]),
                row["age_group"],
                row["country_id"],
                row["country_name"],
                float(row["country_probability"]),
            )


async def main(csv_path: str) -> int:
    path = Path(csv_path)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    settings = get_settings()
    raw_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    conn = await asyncpg.connect(raw_url, ssl="require")

    # Order MUST match the tuple yielded by stream_rows()
    columns = [
        "id", "created_at", "updated_at",
        "name", "gender", "gender_probability",
        "age", "age_group", "country_id", "country_name",
        "country_probability",
    ]

    try:
        before = await conn.fetchval("SELECT COUNT(*) FROM profiles")
        print(f"Rows before: {before:,}")

        # One transaction wraps create + COPY + merge. If anything fails the
        # whole thing rolls back and `profiles` is unchanged.
        #
        # ON COMMIT DROP — the temp table dies at transaction end, which is
        # required behind Neon's connection pooler: the underlying session
        # outlives the script, so a session-scoped temp table would leak
        # between runs and cause DuplicateTableError on the next invocation.
        # The DROP IF EXISTS is belt-and-suspenders for an aborted prior run.
        async with conn.transaction():
            await conn.execute("DROP TABLE IF EXISTS staging_profiles")
            await conn.execute(
                "CREATE TEMP TABLE staging_profiles "
                "(LIKE profiles) ON COMMIT DROP"
            )
            print("Streaming COPY into staging...")
            copied = await conn.copy_records_to_table(
                "staging_profiles",
                records=stream_rows(path),
                columns=columns,
            )
            print(f"  {copied}")

            print("Merging staging -> profiles (skipping name conflicts)...")
            result = await conn.execute("""
                INSERT INTO profiles
                SELECT * FROM staging_profiles
                ON CONFLICT (name) DO NOTHING
            """)
            print(f"  {result}")

        after = await conn.fetchval("SELECT COUNT(*) FROM profiles")
        print(f"Rows after: {after:,} (added {after - before:,})")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", help="Path to the CSV file to load")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.csv_path)))
