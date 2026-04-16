from pydantic import BaseModel, ConfigDict
from datetime import datetime
import uuid


class ProfileCreate(BaseModel):
    name: str


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    gender: str
    gender_probability: float
    sample_size: int
    age: int
    age_group: str
    country_id: str
    country_probability: float
    created_at: datetime


class ProfileListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    gender: str
    age: int
    age_group: str
    country_id: str