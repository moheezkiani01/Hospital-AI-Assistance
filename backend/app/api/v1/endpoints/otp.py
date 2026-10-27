from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.rate_limit_deps import public_rate_limit
from app.db.database import get_db
from app.schemas.p0 import OTPRequest, OTPVerifyRequest
from app.services import audit_service, otp_service


router = APIRouter()


@router.post("/request", dependencies=[Depends(public_rate_limit)])
def request_code(request_data: OTPRequest, db: Session = Depends(get_db)):
    try:
        with audit_service.audit_context(
            hospital_id=request_data.hospital_id,
            actor_type="patient_otp",
            session_id=request_data.session_id,
        ):
            result = otp_service.request_otp(
                db,
                hospital_id=request_data.hospital_id,
                phone=request_data.phone,
                purpose=request_data.purpose,
                session_id=request_data.session_id,
                appointment_id=request_data.appointment_id,
            )
            audit_service.log_explicit_event(
                db,
                action="otp_requested",
                entity_type="OTPChallenge",
                entity_id=result.get("challenge_id"),
                hospital_id=request_data.hospital_id,
                metadata={"purpose": request_data.purpose},
            )
            db.commit()
            return result
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.post("/verify", dependencies=[Depends(public_rate_limit)])
def verify_code(request_data: OTPVerifyRequest, db: Session = Depends(get_db)):
    try:
        result = otp_service.verify_otp(
            db,
            challenge_id=request_data.challenge_id,
            code=request_data.code,
        )
        return result
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
