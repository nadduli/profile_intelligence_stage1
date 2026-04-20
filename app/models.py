from .database import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String


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