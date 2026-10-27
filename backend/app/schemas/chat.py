from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ChatMessageRequest(BaseModel):
    hospital_id: int
    message: str
    session_id: Optional[str] = "default"

    # website / whatsapp
    source: Optional[str] = "website"

    # For WhatsApp integration later.
    # Website will not send this.
    whatsapp_number: Optional[str] = None


class ChatMessageResponse(BaseModel):
    message: str
    answer: str
    intent: str
    sources: List = []
    session_id: Optional[str] = "default"


class ChatLogResponse(BaseModel):
    id: int
    hospital_id: int
    session_id: Optional[str] = "default"
    message: str
    answer: str
    intent: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)