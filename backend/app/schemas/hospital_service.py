from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class HospitalServiceCreate(BaseModel):
    hospital_id: int
    department_id: Optional[int] = None
    name: str
    description: Optional[str] = None


class HospitalServiceUpdate(BaseModel):
    department_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class HospitalServiceResponse(BaseModel):
    id: int
    hospital_id: int
    department_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)