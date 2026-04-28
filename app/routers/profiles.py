import csv
import io
import logging
import math
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Profile, User
from ..schemas import ProfileCreate, ProfileResponse
from ..security.deps import get_current_user, require_role
from ..services.enrichment import enrich_name
from ..services.profile import (
    create_profile,
    delete_profile,
    get_all_profiles_filtered,
    get_profile_by_id,
    get_profile_by_name,
    get_profiles,
    get_stats,
)
from ..services.query_parser import parse_query

CSV_COLUMNS = [
    "id",
    "name",
    "gender",
    "gender_probability",
    "age",
    "age_group",
    "country_id",
    "country_name",
    "country_probability",
    "created_at",
]


def _profile_to_csv_row(p: Profile) -> list[str]:
    """Map a Profile to a row in the spec's column order."""
    return [
        str(p.id),
        p.name,
        p.gender,
        f"{p.gender_probability}",
        str(p.age),
        p.age_group,
        p.country_id,
        p.country_name,
        f"{p.country_probability}",
        p.created_at.isoformat(),
    ]


def _csv_stream(profiles: list[Profile]):
    """Yield CSV bytes one row at a time for StreamingResponse."""
    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow(CSV_COLUMNS)
    yield buf.getvalue()
    buf.seek(0)
    buf.truncate(0)

    for p in profiles:
        writer.writerow(_profile_to_csv_row(p))
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/profiles",
    tags=["profiles"],
    dependencies=[Depends(get_current_user)],
)


def paginated_response(
    request: Request,
    *,
    items: list,
    page: int,
    limit: int,
    total: int,
) -> dict:
    """Build the Stage 3 paginated response envelope.

    Preserves all current query params (filters, sort, etc.) when building
    next/prev links — only `page` and `limit` are overridden.
    """
    total_pages = math.ceil(total / limit) if limit > 0 else 0
    base_path = request.url.path
    current_params = dict(request.query_params)

    def url_for(p: int) -> str:
        params = {**current_params, "page": str(p), "limit": str(limit)}
        return f"{base_path}?{urlencode(params)}"

    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "links": {
            "self": url_for(page),
            "next": url_for(page + 1) if page < total_pages else None,
            "prev": url_for(page - 1) if page > 1 else None,
        },
        "data": items,
    }


@router.get("/search")
async def search_profiles_endpoint(
    q: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    limit: int = 10,
):
    """Natural language search endpoint. Converts plain English into filters."""
    if not q or not q.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing or empty parameter"
        )

    if page < 1 or limit < 1 or limit > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid query parameters"
        )

    filters = parse_query(q)

    if filters is None:
        return JSONResponse(
            status_code=200,
            content={"status": "error", "message": "Unable to interpret query"},
        )

    profiles, total = await get_profiles(
        db,
        page=page,
        limit=limit,
        **filters,
    )

    return paginated_response(
        request,
        items=[ProfileResponse.model_validate(p) for p in profiles],
        page=page,
        limit=limit,
        total=total,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_profile_endpoint(
    body: ProfileCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """Create a new profile with enriched data."""
    if not body.name or not body.name.strip():
        logger.warning("Profile creation attempted with empty name")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required"
        )

    existing_profile = await get_profile_by_name(db, body.name)
    if existing_profile:
        logger.info(f"Profile already exists for name: {body.name}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Profile already exists",
                "data": ProfileResponse.model_validate(existing_profile).model_dump(
                    mode="json"
                ),
            },
        )

    try:
        logger.info(f"Enriching profile for name: {body.name}")
        enriched_data = await enrich_name(body.name)
        logger.debug(f"Enrichment completed for {body.name}")

        new_profile = await create_profile(db, body.name, enriched_data)
        logger.info(
            f"Admin {user.username} created profile {new_profile.id} ({body.name})"
        )

        return {
            "status": "success",
            "data": ProfileResponse.model_validate(new_profile),
        }
    except IntegrityError:
        logger.warning(
            f"Integrity error for name {body.name}, "
            "rolling back and retrieving existing profile"
        )
        await db.rollback()
        existing_profile = await get_profile_by_name(db, body.name)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Profile already exists",
                "data": ProfileResponse.model_validate(existing_profile).model_dump(
                    mode="json"
                ),
            },
        )


@router.get("/stats")
async def get_stats_endpoint(db: AsyncSession = Depends(get_db)):
    """Return aggregate statistics across all profiles."""
    stats = await get_stats(db)
    return {"status": "success", "data": stats}


@router.get("/export")
async def export_profiles_endpoint(
    db: AsyncSession = Depends(get_db),
    format: str = "csv",
    gender: str | None = None,
    age_group: str | None = None,
    country_id: str | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    min_gender_probability: float | None = None,
    min_country_probability: float | None = None,
    sort_by: str = "created_at",
    order: str = "asc",
):
    """Export profiles matching the given filters as CSV."""
    if format != "csv":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only csv format is supported",
        )

    valid_sort_fields = {"age", "created_at", "gender_probability"}
    if sort_by not in valid_sort_fields or order not in {"asc", "desc"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid query parameters",
        )

    profiles = await get_all_profiles_filtered(
        db,
        gender=gender,
        age_group=age_group,
        country_id=country_id,
        min_age=min_age,
        max_age=max_age,
        min_gender_probability=min_gender_probability,
        min_country_probability=min_country_probability,
        sort_by=sort_by,
        order=order,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"profiles_{timestamp}.csv"

    return StreamingResponse(
        _csv_stream(profiles),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{id}")
async def get_profile_endpoint(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Retrieve a profile by its ID."""
    logger.info(f"Fetching profile with ID: {id}")
    profile = await get_profile_by_id(db, id)
    if not profile:
        logger.warning(f"Profile not found with ID: {id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )
    return {"status": "success", "data": ProfileResponse.model_validate(profile)}


@router.get("")
async def list_profiles_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
    gender: str | None = None,
    age_group: str | None = None,
    country_id: str | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    min_gender_probability: float | None = None,
    min_country_probability: float | None = None,
    sort_by: str = "created_at",
    order: str = "asc",
    page: int = 1,
    limit: int = 10,
):
    """List profiles with filtering, sorting, and pagination."""
    valid_sort_fields = {"age", "created_at", "gender_probability"}
    if sort_by not in valid_sort_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid query parameters"
        )

    if order not in {"asc", "desc"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid query parameters"
        )

    if page < 1 or limit < 1 or limit > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid query parameters"
        )

    profiles, total = await get_profiles(
        db,
        gender=gender,
        age_group=age_group,
        country_id=country_id,
        min_age=min_age,
        max_age=max_age,
        min_gender_probability=min_gender_probability,
        min_country_probability=min_country_probability,
        sort_by=sort_by,
        order=order,
        page=page,
        limit=limit,
    )

    return paginated_response(
        request,
        items=[ProfileResponse.model_validate(p) for p in profiles],
        page=page,
        limit=limit,
        total=total,
    )


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile_endpoint(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """Delete a profile by its ID."""
    profile = await get_profile_by_id(db, id)
    if not profile:
        logger.warning(f"Profile not found for deletion with ID: {id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )
    await delete_profile(db, id)
    logger.info(f"Admin {user.username} deleted profile {id}")
