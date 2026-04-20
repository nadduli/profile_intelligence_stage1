import asyncio
import json

import uuid_extensions
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import Base, SessionLocal, engine
from app.models import Profile


async def seed():
    """seed database table with data"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    with open("seed_profiles.json") as f:
        data = json.load(f)

    profiles = data["profiles"]

    rows = [
        {
            "id": uuid_extensions.uuid7(),
            "name": item["name"],
            "gender": item["gender"],
            "gender_probability": item["gender_probability"],
            "age": item["age"],
            "age_group": item["age_group"],
            "country_id": item["country_id"],
            "country_name": item["country_name"],
            "country_probability": item["country_probability"],
        }
        for item in profiles
    ]

    async with SessionLocal() as db:
        stmt = (
            pg_insert(Profile)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["name"])
        )
        result = await db.execute(stmt)
        await db.commit()

    inserted = result.rowcount
    skipped = len(rows) - inserted
    print(f"Seeding complete: {inserted} inserted, {skipped} skipped")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
