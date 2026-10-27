from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.tenant_policy import ensure_hospital_scope, visible_staff_users
from app.api.rate_limit_deps import login_rate_limit
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserCreate, UserResponse
from app.services import auth_service

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(
    user: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    try:
        ensure_hospital_scope(current_user.hospital_id, user.hospital_id)
        return auth_service.create_user(db, user)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(login_rate_limit)],
)
def login(
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    try:
        return auth_service.login_user(db, login_data)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error)
        )


@router.get("/me", response_model=UserResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user)
):
    return current_user


@router.get("/users", response_model=List[UserResponse])
def get_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    return visible_staff_users(db, current_user.hospital_id)