from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.schedule import ScheduleCreate, ScheduleResponse, ScheduleUpdate
from app.services import schedule_service

router = APIRouter()


def check_hospital_permission(current_user: User, hospital_id: int):
    if current_user.hospital_id is not None and current_user.hospital_id != hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this hospital data"
        )


@router.post("/", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
def create_schedule(
    schedule: ScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    check_hospital_permission(current_user, schedule.hospital_id)

    try:
        return schedule_service.create_schedule(db, schedule)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )


@router.get("/", response_model=List[ScheduleResponse])
def get_schedules(
    hospital_id: Optional[int] = Query(default=None),
    doctor_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.hospital_id is not None:
        if hospital_id is not None and hospital_id != current_user.hospital_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this hospital data"
            )

        hospital_id = current_user.hospital_id

    return schedule_service.get_all_schedules(db, hospital_id, doctor_id)


@router.get("/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    schedule = schedule_service.get_schedule_by_id(db, schedule_id)

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Schedule not found"
        )

    check_hospital_permission(current_user, schedule.hospital_id)

    return schedule


@router.put("/{schedule_id}", response_model=ScheduleResponse)
def update_schedule(
    schedule_id: int,
    schedule: ScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    existing_schedule = schedule_service.get_schedule_by_id(db, schedule_id)

    if not existing_schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Schedule not found"
        )

    check_hospital_permission(current_user, existing_schedule.hospital_id)

    try:
        updated_schedule = schedule_service.update_schedule(db, schedule_id, schedule)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )

    return updated_schedule


@router.delete("/{schedule_id}", response_model=ScheduleResponse)
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"]))
):
    existing_schedule = schedule_service.get_schedule_by_id(db, schedule_id)

    if not existing_schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Schedule not found"
        )

    check_hospital_permission(current_user, existing_schedule.hospital_id)

    deleted_schedule = schedule_service.delete_schedule(db, schedule_id)

    return deleted_schedule