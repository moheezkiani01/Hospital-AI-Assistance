from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class FAQCreate(BaseModel):
    hospital_id: int
    question: str
    answer: str
    category: Optional[str] = None


class FAQUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None


class FAQResponse(BaseModel):
    id: int
    hospital_id: int
    question: str
    answer: str
    category: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)