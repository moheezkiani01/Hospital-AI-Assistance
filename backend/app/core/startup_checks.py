"""Checks that run once when the API process starts."""
from __future__ import annotations

import logging
from typing import List

from sqlalchemy.orm import Session

from app.core import secret_policy
from app.core.config import settings
from app.core.security import verify_password
from app.db.database import SessionLocal
from app.models.user import User

logger = logging.getLogger("hospital_ai.security")

# Passwords that were published in this project's old notes or are trivially
# guessable. An admin account still using one of them is a critical finding.
KNOWN_WEAK_PASSWORDS = ("admin123", "admin", "password")
MAX_ADMINS_CHECKED = 5


def find_admins_with_weak_passwords(db: Session) -> List[str]:
    admins = (
        db.query(User)
        .filter(User.role == "admin", User.is_active == True)  # noqa: E712
        .limit(MAX_ADMINS_CHECKED)
        .all()
    )

    flagged: List[str] = []
    for user in admins:
        for candidate in KNOWN_WEAK_PASSWORDS:
            try:
                if verify_password(candidate, user.hashed_password):
                    flagged.append(user.email)
                    break
            except Exception:
                # Unknown/legacy hash format: nothing we can say about it.
                break
    return flagged


def run_startup_checks() -> None:
    production = secret_policy.is_production(settings.APP_ENV)

    db = SessionLocal()
    try:
        flagged = find_admins_with_weak_passwords(db)
    except Exception as exc:  # DB not ready / table missing: do not block startup
        logger.warning("Weak-password startup check skipped: %s", type(exc).__name__)
        return
    finally:
        db.close()

    if not flagged:
        return

    message = (
        "Admin account(s) still use a default/weak password: "
        + ", ".join(flagged)
        + ". Change it with: python scripts/create_admin.py --reset-password"
    )

    if production:
        raise RuntimeError(message)

    logger.critical(message)
