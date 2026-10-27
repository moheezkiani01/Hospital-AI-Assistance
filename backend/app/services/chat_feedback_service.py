from typing import Optional

from sqlalchemy.orm import Session

from app.models.chat_feedback import ChatFeedback
from app.models.chat_log import ChatLog
from app.models.hospital import Hospital
from app.schemas.chat_feedback import ChatFeedbackCreate


def validate_hospital(db: Session, hospital_id: int):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()

    if not hospital:
        raise ValueError("Hospital not found")

    return hospital


def validate_rating(rating: Optional[int]):
    if rating is None:
        return

    if rating < 1 or rating > 5:
        raise ValueError("Rating must be between 1 and 5")


def validate_chat_log(
    db: Session,
    hospital_id: int,
    chat_log_id: Optional[int]
):
    if chat_log_id is None:
        return None

    chat_log = (
        db.query(ChatLog)
        .filter(
            ChatLog.id == chat_log_id,
            ChatLog.hospital_id == hospital_id
        )
        .first()
    )

    if not chat_log:
        raise ValueError("Chat log not found")

    return chat_log


def create_chat_feedback(
    db: Session,
    request_data: ChatFeedbackCreate
):
    validate_hospital(db, request_data.hospital_id)
    validate_rating(request_data.rating)
    validate_chat_log(
        db=db,
        hospital_id=request_data.hospital_id,
        chat_log_id=request_data.chat_log_id
    )

    if request_data.helpful is None and request_data.rating is None and not request_data.comment:
        raise ValueError("Please provide helpful value, rating, or comment")

    feedback = ChatFeedback(
        hospital_id=request_data.hospital_id,
        chat_log_id=request_data.chat_log_id,
        message=request_data.message,
        answer=request_data.answer,
        intent=request_data.intent,
        rating=request_data.rating,
        helpful=request_data.helpful,
        comment=request_data.comment
    )

    db.add(feedback)
    db.commit()
    db.refresh(feedback)

    return feedback


def get_chat_feedbacks(
    db: Session,
    hospital_id: Optional[int] = None
):
    query = db.query(ChatFeedback)

    if hospital_id is not None:
        query = query.filter(ChatFeedback.hospital_id == hospital_id)

    return query.order_by(ChatFeedback.created_at.desc()).all()


def get_chat_feedback_by_id(
    db: Session,
    feedback_id: int
):
    feedback = (
        db.query(ChatFeedback)
        .filter(ChatFeedback.id == feedback_id)
        .first()
    )

    if not feedback:
        raise ValueError("Feedback not found")

    return feedback


def deactivate_chat_feedback(
    db: Session,
    feedback_id: int
):
    feedback = get_chat_feedback_by_id(db, feedback_id)

    feedback.is_active = False

    db.commit()
    db.refresh(feedback)

    return feedback