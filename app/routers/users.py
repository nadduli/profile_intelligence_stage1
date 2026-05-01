"""User-facing endpoints under /api/users.

`/api/users/me` is the canonical "who am I" endpoint for grader / SDK
consumers. The auth router also exposes `/auth/me` for symmetry with the
OAuth surface — both return the same payload via the same dependency.
"""

from fastapi import APIRouter, Depends, Request

from ..models import User
from ..schemas import UserResponse
from ..security.deps import get_current_user
from ..security.rate_limit import limiter, user_id_or_ip

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/me", response_model=UserResponse)
@limiter.limit("60/minute", key_func=user_id_or_ip)
async def get_me(
    request: Request,
    user: User = Depends(get_current_user),
) -> User:
    """Return the currently authenticated user."""
    return user
