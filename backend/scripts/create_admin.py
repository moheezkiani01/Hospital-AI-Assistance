"""Create (or reset the password of) an admin user, with no hard-coded credentials.

Usage (run from the backend/ folder):

    python scripts/create_admin.py --email you@hospital.org --name "Your Name" --hospital-name "City Care Hospital"
    python scripts/create_admin.py --email you@hospital.org --name "Your Name"          # hospital 1 already exists
    python scripts/create_admin.py --email you@hospital.org --reset-password

The password is read from the ADMIN_PASSWORD environment variable if set,
otherwise you are prompted for it (hidden input). It is never printed or stored
anywhere except as a bcrypt hash in the database.

--hospital-id defaults to 1. Pass --super-admin to create an admin that is not tied
to one hospital (can see every hospital).
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core import secret_policy  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.database import SessionLocal, engine  # noqa: E402
from app.models.hospital import Hospital  # noqa: E402
from app.models.user import User  # noqa: E402


def read_password(email: str) -> str:
    password = os.environ.get("ADMIN_PASSWORD", "")

    if not password:
        password = getpass.getpass("New admin password: ")
        if password != getpass.getpass("Repeat password: "):
            raise SystemExit("Passwords do not match.")

    problem = secret_policy.password_problem(password, email)
    if problem:
        raise SystemExit(problem)

    return password


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Administrator")
    parser.add_argument("--hospital-id", type=int, default=1)
    parser.add_argument(
        "--hospital-name",
        help="create this hospital first if it does not exist yet (use on a brand-new database)",
    )
    parser.add_argument("--super-admin", action="store_true", help="not tied to a single hospital")
    parser.add_argument("--reset-password", action="store_true", help="change the password of an existing user")
    args = parser.parse_args()

    email = args.email.strip().lower()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()

        if user and not args.reset_password:
            raise SystemExit(f"{email} already exists. Use --reset-password to change its password.")
        if not user and args.reset_password:
            raise SystemExit(f"{email} does not exist.")

        password = read_password(email)

        if user:
            user.hashed_password = hash_password(password)
            user.is_active = True
            db.commit()
            print(f"Password updated for {email}.")
            return

        hospital_id = None if args.super_admin else args.hospital_id

        if args.hospital_name and not args.super_admin:
            hospital = db.query(Hospital).filter(Hospital.name == args.hospital_name).first()
            if not hospital:
                hospital = Hospital(name=args.hospital_name)
                db.add(hospital)
                db.commit()
                db.refresh(hospital)
                print(f"Hospital '{hospital.name}' created (id {hospital.id}).")
            hospital_id = hospital.id

        if hospital_id is not None and not db.query(Hospital).filter(Hospital.id == hospital_id).first():
            raise SystemExit(
                f"Hospital {hospital_id} does not exist yet. Create it first (see README, 'First run'), "
                "or use --super-admin."
            )

        db.add(
            User(
                hospital_id=hospital_id,
                full_name=args.name,
                email=email,
                hashed_password=hash_password(password),
                role="admin",
                is_active=True,
            )
        )
        db.commit()
        print(f"Admin {email} created.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
