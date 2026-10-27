from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.lab_test import LabTestCreate, LabTestResponse, LabTestUpdate
from app.services import lab_test_service

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


@router.post("/", response_model=LabTestResponse)
def create_lab_test(
    request_data: LabTestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    check_hospital_permission(current_user, request_data.hospital_id)

    try:
        return lab_test_service.create_lab_test(db, request_data)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[LabTestResponse])
def get_lab_tests(
    hospital_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    hospital_id = check_hospital_permission(current_user, hospital_id)

    return lab_test_service.get_lab_tests(db, hospital_id)


@router.get("/{lab_test_id}", response_model=LabTestResponse)
def get_lab_test(
    lab_test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    try:
        lab_test = lab_test_service.get_lab_test_by_id(db, lab_test_id)
        check_hospital_permission(current_user, lab_test.hospital_id)
        return lab_test
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.put("/{lab_test_id}", response_model=LabTestResponse)
def update_lab_test(
    lab_test_id: int,
    request_data: LabTestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    try:
        lab_test = lab_test_service.get_lab_test_by_id(db, lab_test_id)
        check_hospital_permission(current_user, lab_test.hospital_id)
        return lab_test_service.update_lab_test(db, lab_test_id, request_data)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.delete("/{lab_test_id}", response_model=LabTestResponse)
def delete_lab_test(
    lab_test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    try:
        lab_test = lab_test_service.get_lab_test_by_id(db, lab_test_id)
        check_hospital_permission(current_user, lab_test.hospital_id)
        return lab_test_service.delete_lab_test(db, lab_test_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )