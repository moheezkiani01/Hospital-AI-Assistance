from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.doctor import DoctorCreate, DoctorResponse, DoctorUpdate
from app.services import doctor_service

router = APIRouter()


def check_hospital_permission(current_user: User, hospital_id: int):
    if current_user.hospital_id is not None and current_user.hospital_id != hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this hospital data"
        )


@router.post("/", response_model=DoctorResponse, status_code=status.HTTP_201_CREATED)
def create_doctor(
    doctor: DoctorCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    check_hospital_permission(current_user, doctor.hospital_id)

    try:
        return doctor_service.create_doctor(db, doctor)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[DoctorResponse])
def get_doctors(
    hospital_id: Optional[int] = Query(default=None),
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

    return doctor_service.get_all_doctors(db, hospital_id)


@router.get("/{doctor_id}", response_model=DoctorResponse)
def get_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doctor = doctor_service.get_doctor_by_id(db, doctor_id)

    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found"
        )

    check_hospital_permission(current_user, doctor.hospital_id)

    return doctor


@router.put("/{doctor_id}", response_model=DoctorResponse)
def update_doctor(
    doctor_id: int,
    doctor: DoctorUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    existing_doctor = doctor_service.get_doctor_by_id(db, doctor_id)

    if not existing_doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found"
        )

    check_hospital_permission(current_user, existing_doctor.hospital_id)

    updated_doctor = doctor_service.update_doctor(db, doctor_id, doctor)

    return updated_doctor


@router.delete("/{doctor_id}", response_model=DoctorResponse)
def delete_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    existing_doctor = doctor_service.get_doctor_by_id(db, doctor_id)

    if not existing_doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found"
        )

    check_hospital_permission(current_user, existing_doctor.hospital_id)

    deleted_doctor = doctor_service.delete_doctor(db, doctor_id)

    return deleted_doctor