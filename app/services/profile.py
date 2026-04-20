import uuid

from sqlalchemy import and_, delete, func, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Profile


async def get_profile_by_name(db: AsyncSession, name: str) -> Profile | None:
    """Fetch a single profile by name (case-insensitive match)."""
    stmt = select(Profile).where(func.lower(Profile.name) == name.lower())
    result = await db.execute(stmt)
    return result.scalars().first()


async def get_profile_by_id(db: AsyncSession, id: uuid.UUID) -> Profile | None:
    """Fetch a single profile by uuid."""
    stmt = select(Profile).where(Profile.id == id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def get_profiles(
    db: AsyncSession,
    gender: str | None = None,
    country_id: str | None = None,
    age_group: str | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    min_gender_probability: float | None = None,
    min_country_probability: float | None = None,
    sort_by: str = "created_at",
    order: str = "asc",
    page: int = 1,
    limit: int = 10,
) -> tuple[list[Profile], int]:
    """
    Query profiles with optional filters, sorting, and pagination.

    Filters are combined with AND logic — all conditions must match.
    Returns a tuple of (profiles_for_current_page, total_matching_count).
    """
    conditions = []
    if gender:
        conditions.append(Profile.gender == gender.lower())
    if age_group:
        conditions.append(Profile.age_group == age_group.lower())
    if country_id:
        conditions.append(Profile.country_id == country_id.upper())
    if min_age is not None:
        conditions.append(Profile.age >= min_age)
    if max_age is not None:
        conditions.append(Profile.age <= max_age)
    if min_gender_probability is not None:
        conditions.append(Profile.gender_probability >= min_gender_probability)
    if min_country_probability is not None:
        conditions.append(Profile.country_probability >= min_country_probability)

    count_stmt = select(func.count(Profile.id)).where(and_(true(), *conditions))

    total = (await db.execute(count_stmt)).scalar()

    sort_column = {
        "age": Profile.age,
        "gender_probability": Profile.gender_probability,
        "created_at": Profile.created_at,
    }.get(sort_by, Profile.created_at)

    order_fn = sort_column.desc() if order.lower() == "desc" else sort_column.asc()

    stmt = (
        select(Profile)
        .where(and_(true(), *conditions))
        .order_by(order_fn)
        .offset((page - 1) * limit)
        .limit(limit)
    )

    result = await db.execute(stmt)
    return result.scalars().all(), total


async def create_profile(db: AsyncSession, name: str, data: dict) -> Profile:
    """
    Create a new profile with pre-enriched data.

    On duplicate name (race condition), rolls back and returns the existing profile.
    """
    profile = Profile(name=name, **data)
    db.add(profile)
    try:
        await db.flush()
        await db.refresh(profile)
        return profile
    except IntegrityError:
        await db.rollback()
        return await get_profile_by_name(db, name)


async def delete_profile(db: AsyncSession, id: uuid.UUID) -> None:
    """Delete a profile by uuid."""
    stmt = delete(Profile).where(Profile.id == id)
    await db.execute(stmt)


async def get_stats(db: AsyncSession) -> dict:
    """Return aggregate counts across all profiles."""
    total = (await db.execute(select(func.count(Profile.id)))).scalar()

    gender_rows = (
        await db.execute(
            select(Profile.gender, func.count(Profile.id)).group_by(Profile.gender)
        )
    ).all()

    age_group_rows = (
        await db.execute(
            select(Profile.age_group, func.count(Profile.id)).group_by(
                Profile.age_group
            )
        )
    ).all()

    top_countries_rows = (
        await db.execute(
            select(
                Profile.country_id,
                Profile.country_name,
                func.count(Profile.id).label("count"),
            )
            .group_by(Profile.country_id, Profile.country_name)
            .order_by(func.count(Profile.id).desc())
            .limit(10)
        )
    ).all()

    return {
        "total": total,
        "by_gender": {row[0]: row[1] for row in gender_rows},
        "by_age_group": {row[0]: row[1] for row in age_group_rows},
        "top_countries": [
            {"country_id": row[0], "country_name": row[1], "count": row[2]}
            for row in top_countries_rows
        ],
    }
