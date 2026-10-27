from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.emergency_contact import (
    EmergencyContactCreate,
    EmergencyContactResponse,
    EmergencyContactUpdate
)
from app.services import emergency_contact_service

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


@router.post("/", response_model=EmergencyContactResponse)
def create_emergency_contact(
    request_data: EmergencyContactCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    check_hospital_permission(current_user, request_data.hospital_id)

    try:
        return emergency_contact_service.create_emergency_contact(
            db=db,
            request_data=request_data
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[EmergencyContactResponse])
def get_emergency_contacts(
    hospital_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    hospital_id = check_hospital_permission(current_user, hospital_id)

    return emergency_contact_service.get_emergency_contacts(
        db=db,
        hospital_id=hospital_id
    )


@router.get("/{contact_id}", response_model=EmergencyContactResponse)
def get_emergency_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    try:
        emergency_contact = emergency_contact_service.get_emergency_contact_by_id(
            db=db,
            contact_id=contact_id
        )

        check_hospital_permission(current_user, emergency_contact.hospital_id)

        return emergency_contact
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.put("/{contact_id}", response_model=EmergencyContactResponse)
def update_emergency_contact(
    contact_id: int,
    request_data: EmergencyContactUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    try:
        emergency_contact = emergency_contact_service.get_emergency_contact_by_id(
            db=db,
            contact_id=contact_id
        )

        check_hospital_permission(current_user, emergency_contact.hospital_id)

        return emergency_contact_service.update_emergency_contact(
            db=db,
            contact_id=contact_id,
            request_data=request_data
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.delete("/{contact_id}", response_model=EmergencyContactResponse)
def delete_emergency_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    try:
        emergency_contact = emergency_contact_service.get_emergency_contact_by_id(
            db=db,
            contact_id=contact_id
        )

        check_hospital_permission(current_user, emergency_contact.hospital_id)

        return emergency_contact_service.delete_emergency_contact(
            db=db,
            contact_id=contact_id
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )