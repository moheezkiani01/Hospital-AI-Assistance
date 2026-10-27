from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DepartmentCreate(BaseModel):
    hospital_id: int
    name: str
    description: Optional[str] = None


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class DepartmentResponse(BaseModel):
    id: int
    hospital_id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)