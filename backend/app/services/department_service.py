from typing import Optional

from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.hospital import Hospital
from app.schemas.department import DepartmentCreate, DepartmentUpdate


def validate_hospital(db: Session, hospital_id: int):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()

    if not hospital:
        raise ValueError("Hospital not found")

    return hospital


def create_department(db: Session, request_data: DepartmentCreate):
    validate_hospital(db, request_data.hospital_id)

    existing_department = (
        db.query(Department)
        .filter(
            Department.hospital_id == request_data.hospital_id,
            Department.name == request_data.name
        )
        .first()
    )

    if existing_department:
        raise ValueError("Department with this name already exists")

    department = Department(
        hospital_id=request_data.hospital_id,
        name=request_data.name.strip(),
        description=request_data.description
    )

    db.add(department)
    db.commit()
    db.refresh(department)

    return department


def get_departments(db: Session, hospital_id: Optional[int] = None):
    query = db.query(Department)

    if hospital_id is not None:
        query = query.filter(Department.hospital_id == hospital_id)

    return query.order_by(Department.name.asc()).all()


def get_active_departments(db: Session, hospital_id: int):
    return (
        db.query(Department)
        .filter(
            Department.hospital_id == hospital_id,
            Department.is_active == True
        )
        .order_by(Department.name.asc())
        .all()
    )


def get_department_by_id(db: Session, department_id: int):
    department = db.query(Department).filter(Department.id == department_id).first()

    if not department:
        raise ValueError("Department not found")

    return department


def update_department(db: Session, department_id: int, request_data: DepartmentUpdate):
    department = get_department_by_id(db, department_id)

    if request_data.name is not None:
        department.name = request_data.name.strip()

    if request_data.description is not None:
        department.description = request_data.description

    if request_data.is_active is not None:
        department.is_active = request_data.is_active

    db.commit()
    db.refresh(department)

    return department


def delete_department(db: Session, department_id: int):
    department = get_department_by_id(db, department_id)

    department.is_active = False

    db.commit()
    db.refresh(department)

    return department