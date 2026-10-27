from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.unanswered_question import (
    UnansweredQuestionCreate,
    UnansweredQuestionResponse,
    UnansweredQuestionUpdate
)
from app.services import unanswered_question_service

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


@router.post("/", response_model=UnansweredQuestionResponse)
def create_unanswered_question(
    request_data: UnansweredQuestionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    check_hospital_permission(current_user, request_data.hospital_id)

    try:
        return unanswered_question_service.create_unanswered_question(
            db=db,
            request_data=request_data
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[UnansweredQuestionResponse])
def get_unanswered_questions(
    hospital_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    hospital_id = check_hospital_permission(current_user, hospital_id)

    return unanswered_question_service.get_unanswered_questions(
        db=db,
        hospital_id=hospital_id
    )


@router.get("/{question_id}", response_model=UnansweredQuestionResponse)
def get_unanswered_question(
    question_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    try:
        unanswered_question = unanswered_question_service.get_unanswered_question_by_id(
            db=db,
            question_id=question_id
        )

        check_hospital_permission(current_user, unanswered_question.hospital_id)

        return unanswered_question
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.put("/{question_id}", response_model=UnansweredQuestionResponse)
def update_unanswered_question(
    question_id: int,
    request_data: UnansweredQuestionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist"]))
):
    try:
        unanswered_question = unanswered_question_service.get_unanswered_question_by_id(
            db=db,
            question_id=question_id
        )

        check_hospital_permission(current_user, unanswered_question.hospital_id)

        return unanswered_question_service.update_unanswered_question(
            db=db,
            question_id=question_id,
            request_data=request_data
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )


@router.delete("/{question_id}", response_model=UnansweredQuestionResponse)
def deactivate_unanswered_question(
    question_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    try:
        unanswered_question = unanswered_question_service.get_unanswered_question_by_id(
            db=db,
            question_id=question_id
        )

        check_hospital_permission(current_user, unanswered_question.hospital_id)

        return unanswered_question_service.deactivate_unanswered_question(
            db=db,
            question_id=question_id
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )