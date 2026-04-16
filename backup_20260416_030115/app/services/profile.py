from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from ..models import Profile
import uuid


async def get_profile_by_name(db: AsyncSession, name: str) -> Profile | None:
    stmt = select(Profile).where(func.lower(Profile.name) == name.lower())
    result = await db.execute(stmt)
    return result.scalars().first()


async def get_profile_by_id(db: AsyncSession, id: uuid.UUID) -> Profile | None:
    stmt = select(Profile).where(Profile.id == id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def get_profiles(
    db: AsyncSession,
    gender: str | None = None,
    country_id: str | None = None,
    age_group: str | None = None
) -> list[Profile]:
    stmt = select(Profile)
    if gender:
        stmt = stmt.where(Profile.gender.ilike(gender))
    if country_id:
        stmt = stmt.where(Profile.country_id.ilike(country_id))
    if age_group:
        stmt = stmt.where(Profile.age_group.ilike(age_group))
    result = await db.execute(stmt)
    return result.scalars().all()


async def create_profile(db: AsyncSession, name: str, data: dict) -> Profile:
    profile = Profile(name=name, **data)
    db.add(profile)
    try:
        await db.flush()
        await db.refresh(profile)
        return profile
    except IntegrityError:
        # Profile already exists, retrieve it
        await db.rollback()
        return await get_profile_by_name(db, name)

async def delete_profile(db: AsyncSession, id: uuid.UUID) -> None:
    stmt = delete(Profile).where(Profile.id == id)
    await db.execute(stmt)