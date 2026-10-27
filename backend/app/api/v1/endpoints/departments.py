from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.department import DepartmentCreate, DepartmentResponse, DepartmentUpdate
from app.services import department_service

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


@router.post("/", response_model=DepartmentResponse)
def create_department(
    request_data: DepartmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    check_hospital_permission(current_user, request_data.hospital_id)

    try:
        return department_service.create_department(db, request_data)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[DepartmentResponse])
def get_departments(
    hospital_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    hospital_id = check_hospital_permission(current_user, hospital_id)

    return department_service.get_departments(db, hospital_id)


@router.get("/{department_id}", response_model=DepartmentResponse)
def get_department(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    try:
        department = department_service.get_department_by_id(db, department_id)
        check_hospital_permission(current_user, department.hospital_id)
        return department
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.put("/{department_id}", response_model=DepartmentResponse)
def update_department(
    department_id: int,
    request_data: DepartmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    try:
        department = department_service.get_department_by_id(db, department_id)
        check_hospital_permission(current_user, department.hospital_id)
        return department_service.update_department(db, department_id, request_data)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.delete("/{department_id}", response_model=DepartmentResponse)
def delete_department(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    try:
        department = department_service.get_department_by_id(db, department_id)
        check_hospital_permission(current_user, department.hospital_id)
        return department_service.delete_department(db, department_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )