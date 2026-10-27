from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ChatFeedbackCreate(BaseModel):
    hospital_id: int
    chat_log_id: Optional[int] = None

    message: Optional[str] = None
    answer: Optional[str] = None
    intent: Optional[str] = None

    rating: Optional[int] = None
    helpful: Optional[bool] = None
    comment: Optional[str] = None


class ChatFeedbackResponse(BaseModel):
    id: int
    hospital_id: int
    chat_log_id: Optional[int] = None

    message: Optional[str] = None
    answer: Optional[str] = None
    intent: Optional[str] = None

    rating: Optional[int] = None
    helpful: Optional[bool] = None
    comment: Optional[str] = None

    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)