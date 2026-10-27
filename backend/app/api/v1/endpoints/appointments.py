from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentResponse,
    AppointmentUpdate
)
from app.services import appointment_service

router = APIRouter()


def check_hospital_permission(current_user: User, hospital_id: int):
    if current_user.hospital_id is not None and current_user.hospital_id != hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this hospital data"
        )


@router.post("/", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def create_appointment(
    appointment: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    check_hospital_permission(current_user, appointment.hospital_id)

    try:
        return appointment_service.create_appointment(db, appointment)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[AppointmentResponse])
def get_appointments(
    hospital_id: Optional[int] = Query(default=None),
    doctor_id: Optional[int] = Query(default=None),
    patient_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.hospital_id is not None:
        if hospital_id is not None and hospital_id != current_user.hospital_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this hospital data"
            )

        hospital_id = current_user.hospital_id

    return appointment_service.get_all_appointments(
        db,
        hospital_id,
        doctor_id,
        patient_id
    )


# IMPORTANT: This must stay above /{appointment_id}
@router.get("/available-slots")
def get_available_slots(
    hospital_id: int = Query(...),
    doctor_id: int = Query(...),
    appointment_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    check_hospital_permission(current_user, hospital_id)

    try:
        return appointment_service.get_available_slots(
            db,
            hospital_id,
            doctor_id,
            appointment_date
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    appointment = appointment_service.get_appointment_by_id(db, appointment_id)

    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found"
        )

    check_hospital_permission(current_user, appointment.hospital_id)

    return appointment


@router.put("/{appointment_id}", response_model=AppointmentResponse)
def update_appointment(
    appointment_id: int,
    appointment: AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    existing_appointment = appointment_service.get_appointment_by_id(
        db,
        appointment_id
    )

    if not existing_appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found"
        )

    check_hospital_permission(current_user, existing_appointment.hospital_id)

    try:
        updated_appointment = appointment_service.update_appointment(
            db,
            appointment_id,
            appointment
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        ) from error

    return updated_appointment


@router.delete("/{appointment_id}", response_model=AppointmentResponse)
def cancel_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    existing_appointment = appointment_service.get_appointment_by_id(
        db,
        appointment_id
    )

    if not existing_appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found"
        )

    check_hospital_permission(current_user, existing_appointment.hospital_id)

    try:
        cancelled_appointment = appointment_service.cancel_appointment(
            db,
            appointment_id
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        ) from error

    return cancelled_appointment