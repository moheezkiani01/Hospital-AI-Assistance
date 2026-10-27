from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.api.rate_limit_deps import public_rate_limit
from app.db.database import get_db
from app.models.user import User
from app.schemas.chat_feedback import ChatFeedbackCreate, ChatFeedbackResponse
from app.services import chat_feedback_service

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
    response_model=ChatFeedbackResponse,
    dependencies=[Depends(public_rate_limit)],
)
def create_chat_feedback(
    request_data: ChatFeedbackCreate,
    db: Session = Depends(get_db)
):
    try:
        return chat_feedback_service.create_chat_feedback(
            db=db,
            request_data=request_data
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[ChatFeedbackResponse])
def get_chat_feedbacks(
    hospital_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin", "receptionist", "doctor"]))
):
    hospital_id = check_hospital_permission(current_user, hospital_id)

    return chat_feedback_service.get_chat_feedbacks(
        db=db,
        hospital_id=hospital_id
    )


@router.delete("/{feedback_id}", response_model=ChatFeedbackResponse)
def deactivate_chat_feedback(
    feedback_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    try:
        feedback = chat_feedback_service.get_chat_feedback_by_id(
            db=db,
            feedback_id=feedback_id
        )

        check_hospital_permission(current_user, feedback.hospital_id)

        return chat_feedback_service.deactivate_chat_feedback(
            db=db,
            feedback_id=feedback_id
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error)
        )