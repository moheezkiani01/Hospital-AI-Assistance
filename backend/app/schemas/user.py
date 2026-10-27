from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    hospital_id: Optional[int] = None
    full_name: str
    email: str
    password: str
    role: str = "receptionist"


class UserResponse(BaseModel):
    id: int
    hospital_id: Optional[int]
    full_name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)