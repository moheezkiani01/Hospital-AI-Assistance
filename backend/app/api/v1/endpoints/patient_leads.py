from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.api.rate_limit_deps import public_rate_limit
from app.db.database import get_db
from app.models.user import User
from app.schemas.patient_lead import (
    PatientLeadCreate,
    PatientLeadResponse,
    PatientLeadUpdate
)
from app.services import patient_lead_service

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


@router.post(
    "/",
    response_model=PatientLeadResponse,
    dependencies=[Depends(public_rate_limit)],
)
def create_patient_lead(
    request_data: PatientLeadCreate,
    db: Session = Depends(get_db)
):
    try:
        return patient_lead_service.create_patient_lead(
            db=db,
            request_data=request_data
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[PatientLeadResponse])
def get_patient_leads(
    hospital_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    hospital_id = check_hospital_permission(current_user, hospital_id)

    return patient_lead_service.get_patient_leads(
        db=db,
        hospital_id=hospital_id
    )


@router.get("/{lead_id}", response_model=PatientLeadResponse)
def get_patient_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    try:
        lead = patient_lead_service.get_patient_lead_by_id(
            db=db,
            lead_id=lead_id
        )

        check_hospital_permission(current_user, lead.hospital_id)

        return lead
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.put("/{lead_id}", response_model=PatientLeadResponse)
def update_patient_lead(
    lead_id: int,
    request_data: PatientLeadUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    try:
        lead = patient_lead_service.get_patient_lead_by_id(
            db=db,
            lead_id=lead_id
        )

        check_hospital_permission(current_user, lead.hospital_id)

        return patient_lead_service.update_patient_lead(
            db=db,
            lead_id=lead_id,
            request_data=request_data
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.delete("/{lead_id}", response_model=PatientLeadResponse)
def deactivate_patient_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    try:
        lead = patient_lead_service.get_patient_lead_by_id(
            db=db,
            lead_id=lead_id
        )

        check_hospital_permission(current_user, lead.hospital_id)

        return patient_lead_service.deactivate_patient_lead(
            db=db,
            lead_id=lead_id
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )