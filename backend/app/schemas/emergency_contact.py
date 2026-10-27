from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class EmergencyContactCreate(BaseModel):
    hospital_id: int
    title: str
    phone_number: str
    contact_type: Optional[str] = None
    description: Optional[str] = None


class EmergencyContactUpdate(BaseModel):
    title: Optional[str] = None
    phone_number: Optional[str] = None
    contact_type: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class EmergencyContactResponse(BaseModel):
    id: int
    hospital_id: int
    title: str
    phone_number: str
    contact_type: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)