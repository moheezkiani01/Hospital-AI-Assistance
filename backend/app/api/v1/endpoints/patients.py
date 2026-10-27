from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.patient import PatientCreate, PatientResponse, PatientUpdate
from app.services import patient_service

router = APIRouter()


def check_hospital_permission(current_user: User, hospital_id: int):
    if current_user.hospital_id is not None and current_user.hospital_id != hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this hospital data"
        )


@router.post("/", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
def create_patient(
    patient: PatientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    check_hospital_permission(current_user, patient.hospital_id)

    try:
        return patient_service.create_patient(db, patient)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[PatientResponse])
def get_patients(
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

    return patient_service.get_all_patients(db, hospital_id)


@router.get("/{patient_id}", response_model=PatientResponse)
def get_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    patient = patient_service.get_patient_by_id(db, patient_id)

    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found"
        )

    check_hospital_permission(current_user, patient.hospital_id)

    return patient


@router.put("/{patient_id}", response_model=PatientResponse)
def update_patient(
    patient_id: int,
    patient: PatientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    existing_patient = patient_service.get_patient_by_id(db, patient_id)

    if not existing_patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found"
        )

    check_hospital_permission(current_user, existing_patient.hospital_id)

    updated_patient = patient_service.update_patient(db, patient_id, patient)

    return updated_patient


@router.delete("/{patient_id}", response_model=PatientResponse)
def delete_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    existing_patient = patient_service.get_patient_by_id(db, patient_id)

    if not existing_patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found"
        )

    check_hospital_permission(current_user, existing_patient.hospital_id)

    deleted_patient = patient_service.delete_patient(db, patient_id)

    return deleted_patient