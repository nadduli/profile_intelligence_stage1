from .database import Base
from sqlalchemy.orm import Mapped, mapped_column


class Profile(Base):
    """Profile model representing a user profile in the database."""

    name: Mapped[str] = mapped_column(unique=True, index=True)
    gender: Mapped[str]
    gender_probability: Mapped[float]
    sample_size: Mapped[int]
    age: Mapped[int]
    age_group: Mapped[str]
    country_id: Mapped[str]
    country_probability: Mapped[float]

    def __repr__(self) -> str:
        return (
            f"Profile(name={self.name}, gender={self.gender}, "
            f"age={self.age}, age_group={self.age_group}, country_id={self.country_id})"
        )