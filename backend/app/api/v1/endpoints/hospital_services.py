from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.hospital_service import (
    HospitalServiceCreate,
    HospitalServiceResponse,
    HospitalServiceUpdate
)
from app.services import hospital_service_service

router = APIRouter()


def check_hospital_permission(current_user: User, hospital_id: Optional[int]):
    if current_user.hospital_id is not None:
        if hospital_id is not None and hospital_id != current_user.hospital_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this hospital data"
            )

        return current_user.hospital_id

    return hospital_id


@router.post("/", response_model=HospitalServiceResponse)
def create_hospital_service(
    request_data: HospitalServiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    check_hospital_permission(current_user, request_data.hospital_id)

    try:
        return hospital_service_service.create_hospital_service(db, request_data)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[HospitalServiceResponse])
def get_hospital_services(
    hospital_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    hospital_id = check_hospital_permission(current_user, hospital_id)

    return hospital_service_service.get_hospital_services(db, hospital_id)


@router.get("/{service_id}", response_model=HospitalServiceResponse)
def get_hospital_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    try:
        hospital_service = hospital_service_service.get_hospital_service_by_id(
            db,
            service_id
        )
        check_hospital_permission(current_user, hospital_service.hospital_id)
        return hospital_service
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.put("/{service_id}", response_model=HospitalServiceResponse)
def update_hospital_service(
    service_id: int,
    request_data: HospitalServiceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    try:
        hospital_service = hospital_service_service.get_hospital_service_by_id(
            db,
            service_id
        )
        check_hospital_permission(current_user, hospital_service.hospital_id)
        return hospital_service_service.update_hospital_service(
            db,
            service_id,
            request_data
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.delete("/{service_id}", response_model=HospitalServiceResponse)
def delete_hospital_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    try:
        hospital_service = hospital_service_service.get_hospital_service_by_id(
            db,
            service_id
        )
        check_hospital_permission(current_user, hospital_service.hospital_id)
        return hospital_service_service.delete_hospital_service(db, service_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )