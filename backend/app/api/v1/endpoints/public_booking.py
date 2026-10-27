from datetime import date, datetime
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.rate_limit_deps import public_rate_limit
from app.core.config import settings
from app.db.database import get_db
from app.schemas.public_booking import (
    PublicAppointmentStatusRequest,
    PublicAppointmentStatusResponse,
    PublicAvailableSlotsResponse,
    PublicBookAppointmentRequest,
    PublicBookAppointmentResponse,
    PublicCancelAppointmentRequest,
    PublicCancelAppointmentResponse,
    PublicDoctorResponse,
    PublicRescheduleAppointmentRequest,
    PublicRescheduleAppointmentResponse,
)
from app.services import audit_service, otp_service, public_booking_service

router = APIRouter()


def _require_otp_if_enabled(
    db: Session,
    *,
    otp_token: Optional[str],
    hospital_id: int,
    phone: str,
    purpose: str,
    appointment_id: Optional[int],
    consume: bool,
):
    if not bool(getattr(settings, "OTP_REQUIRED_FOR_SENSITIVE_ACTIONS", False)):
        return None

    return otp_service.validate_verification_token(
        db,
        token=otp_token or "",
        hospital_id=hospital_id,
        phone=phone,
        purpose=purpose,
        appointment_id=appointment_id,
        consume=consume,
    )


@router.get("/doctors", response_model=List[PublicDoctorResponse], dependencies=[Depends(public_rate_limit)])
def get_public_doctors(
    hospital_id: int = Query(...),
    db: Session = Depends(get_db)
):
    try:
        return public_booking_service.get_public_doctors(db=db, hospital_id=hospital_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


@router.get("/available-slots", response_model=PublicAvailableSlotsResponse, dependencies=[Depends(public_rate_limit)])
def get_available_slots(
    hospital_id: int = Query(...),
    doctor_id: int = Query(...),
    appointment_date: date = Query(...),
    db: Session = Depends(get_db)
):
    try:
        return public_booking_service.get_available_slots(
            db=db,
            hospital_id=hospital_id,
            doctor_id=doctor_id,
            appointment_date=appointment_date,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.post("/book-appointment", response_model=PublicBookAppointmentResponse, dependencies=[Depends(public_rate_limit)])
def book_public_appointment(
    request_data: PublicBookAppointmentRequest,
    db: Session = Depends(get_db)
):
    request_id = uuid4().hex
    try:
        with audit_service.audit_context(
            hospital_id=request_data.hospital_id,
            actor_type="public_booking",
            request_id=request_id,
        ):
            return public_booking_service.book_public_appointment(db=db, request_data=request_data)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.post("/cancel-appointment", response_model=PublicCancelAppointmentResponse, dependencies=[Depends(public_rate_limit)])
def cancel_public_appointment(
    request_data: PublicCancelAppointmentRequest,
    db: Session = Depends(get_db),
    otp_token: Optional[str] = Header(default=None, alias="X-OTP-Token"),
):
    request_id = uuid4().hex
    try:
        otp_challenge = _require_otp_if_enabled(
            db,
            otp_token=otp_token,
            hospital_id=request_data.hospital_id,
            phone=request_data.patient_phone,
            purpose="cancel_appointment",
            appointment_id=request_data.appointment_id,
            consume=False,
        )
        with audit_service.audit_context(
            hospital_id=request_data.hospital_id,
            actor_type="public_booking",
            request_id=request_id,
        ):
            result = public_booking_service.cancel_public_appointment(db=db, request_data=request_data)
            if otp_challenge is not None:
                otp_challenge.used_at = datetime.utcnow()
                db.commit()
            return result
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.post("/reschedule-appointment", response_model=PublicRescheduleAppointmentResponse, dependencies=[Depends(public_rate_limit)])
def reschedule_public_appointment(
    request_data: PublicRescheduleAppointmentRequest,
    db: Session = Depends(get_db),
    otp_token: Optional[str] = Header(default=None, alias="X-OTP-Token"),
):
    request_id = uuid4().hex
    try:
        otp_challenge = _require_otp_if_enabled(
            db,
            otp_token=otp_token,
            hospital_id=request_data.hospital_id,
            phone=request_data.patient_phone,
            purpose="reschedule_appointment",
            appointment_id=request_data.appointment_id,
            consume=False,
        )
        with audit_service.audit_context(
            hospital_id=request_data.hospital_id,
            actor_type="public_booking",
            request_id=request_id,
        ):
            result = public_booking_service.reschedule_public_appointment(db=db, request_data=request_data)
            if otp_challenge is not None:
                otp_challenge.used_at = datetime.utcnow()
                db.commit()
            return result
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.post("/appointment-status", response_model=PublicAppointmentStatusResponse, dependencies=[Depends(public_rate_limit)])
def get_appointment_status(
    request_data: PublicAppointmentStatusRequest,
    db: Session = Depends(get_db),
    otp_token: Optional[str] = Header(default=None, alias="X-OTP-Token"),
):
    try:
        _require_otp_if_enabled(
            db,
            otp_token=otp_token,
            hospital_id=request_data.hospital_id,
            phone=request_data.patient_phone,
            purpose="appointment_status",
            appointment_id=request_data.appointment_id,
            consume=False,
        )
        return public_booking_service.get_public_appointment_status(db=db, request_data=request_data)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
