from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DoctorBase(BaseModel):
    hospital_id: int
    name: str
    specialization: str
    consultation_fee: float
    phone: Optional[str] = None


class DoctorCreate(DoctorBase):
    pass


class DoctorUpdate(BaseModel):
    name: Optional[str] = None
    specialization: Optional[str] = None
    consultation_fee: Optional[float] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None


class DoctorResponse(DoctorBase):
    id: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)