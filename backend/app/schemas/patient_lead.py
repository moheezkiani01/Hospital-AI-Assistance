from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PatientLeadCreate(BaseModel):
    hospital_id: int
    name: str
    phone: str
    question: Optional[str] = None
    interested_service: Optional[str] = None


class PatientLeadUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    question: Optional[str] = None
    interested_service: Optional[str] = None
    status: Optional[str] = None
    is_active: Optional[bool] = None


class PatientLeadResponse(BaseModel):
    id: int
    hospital_id: int
    name: str
    phone: str
    question: Optional[str] = None
    interested_service: Optional[str] = None
    status: str
    source: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)