from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.hospital import HospitalCreate, HospitalResponse, HospitalUpdate
from app.services import hospital_service

router = APIRouter()


def check_hospital_permission(current_user: User, hospital_id: int):
    if current_user.hospital_id is not None and current_user.hospital_id != hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this hospital data"
        )


@router.post("/", response_model=HospitalResponse, status_code=status.HTTP_201_CREATED)
def create_hospital(
    hospital: HospitalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    return hospital_service.create_hospital(db, hospital)


@router.get("/", response_model=List[HospitalResponse])
def get_hospitals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    hospitals = hospital_service.get_all_hospitals(db)

    if current_user.hospital_id is not None:
        hospitals = [
            hospital for hospital in hospitals
            if hospital.id == current_user.hospital_id
        ]

    return hospitals


@router.get("/{hospital_id}", response_model=HospitalResponse)
def get_hospital(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    check_hospital_permission(current_user, hospital_id)

    hospital = hospital_service.get_hospital_by_id(db, hospital_id)

    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found"
        )

    return hospital


@router.put("/{hospital_id}", response_model=HospitalResponse)
def update_hospital(
    hospital_id: int,
    hospital: HospitalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    check_hospital_permission(current_user, hospital_id)

    try:
        updated_hospital = hospital_service.update_hospital(
            db,
            hospital_id,
            hospital
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )

    if not updated_hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found"
        )

    return updated_hospital


@router.delete("/{hospital_id}", response_model=HospitalResponse)
def delete_hospital(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    check_hospital_permission(current_user, hospital_id)

    deleted_hospital = hospital_service.delete_hospital(db, hospital_id)

    if not deleted_hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found"
        )

    return deleted_hospital