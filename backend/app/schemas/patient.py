from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PatientBase(BaseModel):
    hospital_id: int
    name: str
    phone: str
    email: Optional[str] = None


class PatientCreate(PatientBase):
    pass


class PatientUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class PatientResponse(PatientBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)