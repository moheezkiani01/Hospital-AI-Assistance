from typing import Optional

from sqlalchemy.orm import Session

from app.models.hospital import Hospital
from app.models.unanswered_question import UnansweredQuestion
from app.schemas.unanswered_question import (
    UnansweredQuestionCreate,
    UnansweredQuestionUpdate
)


def validate_hospital(db: Session, hospital_id: int):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()

    if not hospital:
        raise ValueError("Hospital not found")

    return hospital


def create_unanswered_question(
    db: Session,
    request_data: UnansweredQuestionCreate
):
    validate_hospital(db, request_data.hospital_id)

    question = request_data.question.strip()

    if not question:
        raise ValueError("Question is required")

    existing_question = (
        db.query(UnansweredQuestion)
        .filter(
            UnansweredQuestion.hospital_id == request_data.hospital_id,
            UnansweredQuestion.question == question,
            UnansweredQuestion.is_active == True
        )
        .first()
    )

    if existing_question:
        return existing_question

    unanswered_question = UnansweredQuestion(
        hospital_id=request_data.hospital_id,
        question=question,
        suggested_action=request_data.suggested_action,
        status="new"
    )

    db.add(unanswered_question)
    db.commit()
    db.refresh(unanswered_question)

    return unanswered_question


def get_unanswered_questions(
    db: Session,
    hospital_id: Optional[int] = None
):
    query = db.query(UnansweredQuestion)

    if hospital_id is not None:
        query = query.filter(UnansweredQuestion.hospital_id == hospital_id)

    return query.order_by(UnansweredQuestion.created_at.desc()).all()


def get_unanswered_question_by_id(
    db: Session,
    question_id: int
):
    unanswered_question = (
        db.query(UnansweredQuestion)
        .filter(UnansweredQuestion.id == question_id)
        .first()
    )

    if not unanswered_question:
        raise ValueError("Unanswered question not found")

    return unanswered_question


def update_unanswered_question(
    db: Session,
    question_id: int,
    request_data: UnansweredQuestionUpdate
):
    unanswered_question = get_unanswered_question_by_id(
        db=db,
        question_id=question_id
    )

    if request_data.suggested_action is not None:
        unanswered_question.suggested_action = request_data.suggested_action

    if request_data.status is not None:
        unanswered_question.status = request_data.status

    if request_data.is_active is not None:
        unanswered_question.is_active = request_data.is_active

    db.commit()
    db.refresh(unanswered_question)

    return unanswered_question


def deactivate_unanswered_question(
    db: Session,
    question_id: int
):
    unanswered_question = get_unanswered_question_by_id(
        db=db,
        question_id=question_id
    )

    unanswered_question.is_active = False

    db.commit()
    db.refresh(unanswered_question)

    return unanswered_question