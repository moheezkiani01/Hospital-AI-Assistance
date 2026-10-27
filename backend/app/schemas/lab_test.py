from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class LabTestCreate(BaseModel):
    hospital_id: int
    department_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    price: Optional[float] = None
    sample_type: Optional[str] = None
    report_time: Optional[str] = None


class LabTestUpdate(BaseModel):
    department_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    sample_type: Optional[str] = None
    report_time: Optional[str] = None
    is_active: Optional[bool] = None


class LabTestResponse(BaseModel):
    id: int
    hospital_id: int
    department_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    price: Optional[float] = None
    sample_type: Optional[str] = None
    report_time: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)