"""Multi-hospital authorization boundaries for staff administration.

A hospital-scoped admin may only manage users inside their own hospital.
A global admin (hospital_id=None) retains platform-wide access.
"""

from sqlalchemy.orm import Session

from app.models.user import User


def ensure_hospital_scope(actor_hospital_id: int | None, target_hospital_id: int | None) -> None:
    if actor_hospital_id is not None and actor_hospital_id != target_hospital_id:
        raise PermissionError("You do not have permission to manage users in this hospital")


def visible_staff_users(db: Session, actor_hospital_id: int | None) -> list[User]:
    query = db.query(User)
    if actor_hospital_id is not None:
        query = query.filter(User.hospital_id == actor_hospital_id)
    return query.all()
