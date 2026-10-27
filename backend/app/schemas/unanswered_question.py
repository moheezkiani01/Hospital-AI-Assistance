from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class UnansweredQuestionCreate(BaseModel):
    hospital_id: int
    question: str
    suggested_action: Optional[str] = None


class UnansweredQuestionUpdate(BaseModel):
    suggested_action: Optional[str] = None
    status: Optional[str] = None
    is_active: Optional[bool] = None


class UnansweredQuestionResponse(BaseModel):
    id: int
    hospital_id: int
    question: str
    suggested_action: Optional[str] = None
    status: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)