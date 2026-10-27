from typing import Optional

from pydantic import BaseModel, Field


class OTPRequest(BaseModel):
    hospital_id: int
    phone: str
    purpose: str
    session_id: Optional[str] = None
    appointment_id: Optional[int] = None


class OTPVerifyRequest(BaseModel):
    challenge_id: int
    code: str = Field(min_length=4, max_length=8)
