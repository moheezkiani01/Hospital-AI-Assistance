from typing import Optional

from sqlalchemy.orm import Session

from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.schedule import Schedule
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate


def create_schedule(db: Session, schedule_data: ScheduleCreate):
    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == schedule_data.hospital_id)
        .first()
    )

    if not hospital:
        raise ValueError("Hospital not found")

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.id == schedule_data.doctor_id,
            Doctor.hospital_id == schedule_data.hospital_id
        )
        .first()
    )

    if not doctor:
        raise ValueError("Doctor not found in this hospital")

    if schedule_data.start_time >= schedule_data.end_time:
        raise ValueError("Start time must be before end time")

    new_schedule = Schedule(**schedule_data.model_dump())

    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)

    return new_schedule


def get_all_schedules(
    db: Session,
    hospital_id: Optional[int] = None,
    doctor_id: Optional[int] = None
):
    query = db.query(Schedule)

    if hospital_id:
        query = query.filter(Schedule.hospital_id == hospital_id)

    if doctor_id:
        query = query.filter(Schedule.doctor_id == doctor_id)

    return query.all()


def get_schedule_by_id(db: Session, schedule_id: int):
    return db.query(Schedule).filter(Schedule.id == schedule_id).first()


def update_schedule(db: Session, schedule_id: int, schedule_data: ScheduleUpdate):
    schedule = get_schedule_by_id(db, schedule_id)

    if not schedule:
        return None

    update_data = schedule_data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(schedule, key, value)

    if schedule.start_time >= schedule.end_time:
        raise ValueError("Start time must be before end time")

    db.commit()
    db.refresh(schedule)

    return schedule


def delete_schedule(db: Session, schedule_id: int):
    schedule = get_schedule_by_id(db, schedule_id)

    if not schedule:
        return None

    schedule.is_active = False
    db.commit()
    db.refresh(schedule)

    return schedule