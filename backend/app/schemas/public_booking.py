from datetime import date, time
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class PublicDoctorResponse(BaseModel):
    id: int
    hospital_id: int
    name: str
    specialization: str
    consultation_fee: Optional[float] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class PublicAvailableSlotsResponse(BaseModel):
    hospital_id: int
    doctor_id: int
    doctor_name: str
    appointment_date: date
    available_slots: List[str]


class PublicBookAppointmentRequest(BaseModel):
    hospital_id: int
    doctor_id: int

    patient_name: str
    patient_phone: str
    patient_email: Optional[str] = None

    appointment_date: date
    appointment_time: time
    reason: Optional[str] = None


class PublicBookAppointmentResponse(BaseModel):
    message: str
    appointment_id: int
    patient_id: int
    doctor_id: int
    doctor_name: str
    appointment_date: date
    appointment_time: time
    status: str


class PublicCancelAppointmentRequest(BaseModel):
    hospital_id: int
    appointment_id: int
    patient_phone: str


class PublicCancelAppointmentResponse(BaseModel):
    message: str
    appointment_id: int
    patient_id: int
    doctor_id: int
    appointment_date: date
    appointment_time: time
    status: str


class PublicRescheduleAppointmentRequest(BaseModel):
    hospital_id: int
    appointment_id: int
    patient_phone: str

    doctor_id: int
    appointment_date: date
    appointment_time: time


class PublicRescheduleAppointmentResponse(BaseModel):
    message: str
    appointment_id: int
    patient_id: int
    doctor_id: int
    doctor_name: str
    appointment_date: date
    appointment_time: time
    status: str


class PublicAppointmentStatusRequest(BaseModel):
    hospital_id: int
    appointment_id: int
    patient_phone: str


class PublicAppointmentStatusResponse(BaseModel):
    appointment_id: int
    patient_id: int
    doctor_id: int
    doctor_name: str
    patient_name: str
    appointment_date: date
    appointment_time: time
    status: str
    reason: Optional[str] = None