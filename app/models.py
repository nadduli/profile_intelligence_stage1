import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Profile(Base):
    """Profile model representing a user profile in the database."""

    name: Mapped[str] = mapped_column(unique=True, index=True)
    gender: Mapped[str]
    gender_probability: Mapped[float]
    age: Mapped[int]
    age_group: Mapped[str] = mapped_column(String, index=True)
    country_id: Mapped[str] = mapped_column(String(20), index=True)
    country_name: Mapped[str] = mapped_column(String)
    country_probability: Mapped[float]

    def __repr__(self) -> str:
        return (
            f"Profile(name={self.name}, gender={self.gender}, "
            f"age={self.age}, age_group={self.age_group}, country_id={self.country_id})"
        )


class User(Base):
    """Authenticated user. Created or updated when a GitHub OAuth login completes."""

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'analyst')", name="users_role_check"),
    )

    github_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String)
    role: Mapped[str] = mapped_column(String(16), server_default="analyst")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(Base):
    """Refresh token issued during OAuth login or rotation. Hashed before storage."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
