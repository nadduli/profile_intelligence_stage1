from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..schemas import ProfileCreate, ProfileResponse, ProfileListItem
from ..services.enrichment import enrich_name
from ..services.profile import get_profile_by_name, create_profile, get_profile_by_id, get_profiles, delete_profile
import uuid

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_profile_endpoint(
    body: ProfileCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new profile with enriched data."""
    if not body.name or not body.name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Name is required"
        )

    existing_profile = await get_profile_by_name(db, body.name)
    if existing_profile:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Profile already exists",
                "data": ProfileResponse.model_validate(existing_profile).model_dump(mode="json"),
            },
        )

    enriched_data = await enrich_name(body.name)
    new_profile = await create_profile(db, body.name, enriched_data)
    return {
        "status": "success",
        "data": ProfileResponse.model_validate(new_profile)
    }


@router.get("/{id}")
async def get_profile_endpoint(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve a profile by its ID."""
    profile = await get_profile_by_id(db, id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )
    return {
        "status": "success",
        "data": ProfileResponse.model_validate(profile)
    }


@router.get("")
async def list_profiles_endpoint(
    db: AsyncSession = Depends(get_db),
    gender: str | None = None,
    country_id: str | None = None,
    age_group: str | None = None
):
    """List all profiles with optional filters."""
    profiles = await get_profiles(db, gender=gender, country_id=country_id, age_group=age_group)
    return {
        "status": "success",
        "count": len(profiles),
        "data": [ProfileListItem.model_validate(p) for p in profiles]
    }


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile_endpoint(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """Delete a profile by its ID."""
    profile = await get_profile_by_id(db, id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )
    await delete_profile(db, id)