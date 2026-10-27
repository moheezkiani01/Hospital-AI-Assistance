from typing import Optional

from sqlalchemy.orm import Session

from app.models.faq import FAQ
from app.models.hospital import Hospital
from app.schemas.faq import FAQCreate, FAQUpdate


def validate_hospital(db: Session, hospital_id: int):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()

    if not hospital:
        raise ValueError("Hospital not found")

    return hospital


def create_faq(
    db: Session,
    request_data: FAQCreate
):
    validate_hospital(db, request_data.hospital_id)

    question = request_data.question.strip()
    answer = request_data.answer.strip()

    if not question:
        raise ValueError("FAQ question is required")

    if not answer:
        raise ValueError("FAQ answer is required")

    existing_faq = (
        db.query(FAQ)
        .filter(
            FAQ.hospital_id == request_data.hospital_id,
            FAQ.question == question
        )
        .first()
    )

    if existing_faq:
        raise ValueError("FAQ with this question already exists")

    faq = FAQ(
        hospital_id=request_data.hospital_id,
        question=question,
        answer=answer,
        category=request_data.category
    )

    db.add(faq)
    db.commit()
    db.refresh(faq)

    return faq


def get_faqs(
    db: Session,
    hospital_id: Optional[int] = None
):
    query = db.query(FAQ)

    if hospital_id is not None:
        query = query.filter(FAQ.hospital_id == hospital_id)

    return query.order_by(FAQ.created_at.desc()).all()


def get_active_faqs(
    db: Session,
    hospital_id: int
):
    return (
        db.query(FAQ)
        .filter(
            FAQ.hospital_id == hospital_id,
            FAQ.is_active == True
        )
        .order_by(FAQ.created_at.desc())
        .all()
    )


def get_faq_by_id(
    db: Session,
    faq_id: int
):
    faq = (
        db.query(FAQ)
        .filter(FAQ.id == faq_id)
        .first()
    )

    if not faq:
        raise ValueError("FAQ not found")

    return faq


def update_faq(
    db: Session,
    faq_id: int,
    request_data: FAQUpdate
):
    faq = get_faq_by_id(db, faq_id)

    if request_data.question is not None:
        question = request_data.question.strip()

        if not question:
            raise ValueError("FAQ question cannot be empty")

        faq.question = question

    if request_data.answer is not None:
        answer = request_data.answer.strip()

        if not answer:
            raise ValueError("FAQ answer cannot be empty")

        faq.answer = answer

    if request_data.category is not None:
        faq.category = request_data.category

    if request_data.is_active is not None:
        faq.is_active = request_data.is_active

    db.commit()
    db.refresh(faq)

    return faq


def deactivate_faq(
    db: Session,
    faq_id: int
):
    faq = get_faq_by_id(db, faq_id)

    faq.is_active = False

    db.commit()
    db.refresh(faq)

    return faq


def calculate_faq_score(message: str, question: str, category: Optional[str] = None):
    message_words = set(message.lower().replace("?", "").split())
    question_words = set(question.lower().replace("?", "").split())

    score = len(message_words.intersection(question_words))

    if category:
        category_words = set(category.lower().split())
        score += len(message_words.intersection(category_words))

    return score


def find_best_faq_answer(
    db: Session,
    hospital_id: int,
    message: str
):
    faqs = get_active_faqs(db=db, hospital_id=hospital_id)

    if not faqs:
        return None

    best_faq = None
    best_score = 0

    for faq in faqs:
        score = calculate_faq_score(
            message=message,
            question=faq.question,
            category=faq.category
        )

        if score > best_score:
            best_score = score
            best_faq = faq

    if best_faq and best_score >= 2:
        return best_faq.answer

    return None