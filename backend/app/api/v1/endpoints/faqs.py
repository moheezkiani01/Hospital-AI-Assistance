from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.faq import FAQCreate, FAQResponse, FAQUpdate
from app.services import faq_service

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


@router.post("/", response_model=FAQResponse)
def create_faq(
    request_data: FAQCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    check_hospital_permission(current_user, request_data.hospital_id)

    try:
        return faq_service.create_faq(
            db=db,
            request_data=request_data
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[FAQResponse])
def get_faqs(
    hospital_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    hospital_id = check_hospital_permission(current_user, hospital_id)

    return faq_service.get_faqs(
        db=db,
        hospital_id=hospital_id
    )


@router.get("/{faq_id}", response_model=FAQResponse)
def get_faq(
    faq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    try:
        faq = faq_service.get_faq_by_id(
            db=db,
            faq_id=faq_id
        )

        check_hospital_permission(current_user, faq.hospital_id)

        return faq
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.put("/{faq_id}", response_model=FAQResponse)
def update_faq(
    faq_id: int,
    request_data: FAQUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    try:
        faq = faq_service.get_faq_by_id(
            db=db,
            faq_id=faq_id
        )

        check_hospital_permission(current_user, faq.hospital_id)

        return faq_service.update_faq(
            db=db,
            faq_id=faq_id,
            request_data=request_data
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.delete("/{faq_id}", response_model=FAQResponse)
def deactivate_faq(
    faq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    try:
        faq = faq_service.get_faq_by_id(
            db=db,
            faq_id=faq_id
        )

        check_hospital_permission(current_user, faq.hospital_id)

        return faq_service.deactivate_faq(
            db=db,
            faq_id=faq_id
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )