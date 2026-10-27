from sqlalchemy.orm import Session

from app.core import secret_policy
from app.core.security import create_access_token, hash_password, verify_password
from app.models.hospital import Hospital
from app.models.user import User
from app.schemas.auth import LoginRequest
from app.schemas.user import UserCreate


ALLOWED_ROLES = ["admin", "receptionist", "doctor"]


def create_user(db: Session, user_data: UserCreate):
    if user_data.role not in ALLOWED_ROLES:
        raise ValueError("Invalid role")

    password_issue = secret_policy.password_problem(user_data.password, user_data.email)
    if password_issue:
        raise ValueError(password_issue)

    existing_user = (
        db.query(User)
        .filter(User.email == user_data.email)
        .first()
    )

    if existing_user:
        raise ValueError("User with this email already exists")

    if user_data.hospital_id:
        hospital = (
            db.query(Hospital)
            .filter(Hospital.id == user_data.hospital_id)
            .first()
        )

        if not hospital:
            raise ValueError("Hospital not found")

    new_user = User(
        hospital_id=user_data.hospital_id,
        full_name=user_data.full_name,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        role=user_data.role
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


def login_user(db: Session, login_data: LoginRequest):
    user = (
        db.query(User)
        .filter(User.email == login_data.email)
        .first()
    )

    if not user:
        raise ValueError("Invalid email or password")

    if not verify_password(login_data.password, user.hashed_password):
        raise ValueError("Invalid email or password")

    if not user.is_active:
        raise ValueError("User account is inactive")

    access_token = create_access_token(
        subject=str(user.id),
        role=user.role,
        hospital_id=user.hospital_id
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "hospital_id": user.hospital_id
    }


def get_all_users(db: Session):
    return db.query(User).all()