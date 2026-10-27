from datetime import datetime, time
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ScheduleBase(BaseModel):
    hospital_id: int
    doctor_id: int
    day_of_week: str
    start_time: time
    end_time: time
    slot_duration_minutes: int = 30


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleUpdate(BaseModel):
    day_of_week: Optional[str] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    slot_duration_minutes: Optional[int] = None
    is_active: Optional[bool] = None


class ScheduleResponse(ScheduleBase):
    id: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)