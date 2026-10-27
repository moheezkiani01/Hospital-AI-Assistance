from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AppointmentBase(BaseModel):
    hospital_id: int
    doctor_id: int
    patient_id: int
    appointment_date: date
    appointment_time: time
    reason: Optional[str] = None


class AppointmentCreate(AppointmentBase):
    pass


class AppointmentUpdate(BaseModel):
    status: Optional[str] = None
    reason: Optional[str] = None


class AppointmentResponse(AppointmentBase):
    id: int
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)