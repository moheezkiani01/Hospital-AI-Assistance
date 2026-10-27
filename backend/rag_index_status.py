import argparse
import json

from app.db.base import Base
from app.db.database import SessionLocal, engine
from app.services.rag_index_service import get_hospital_index_health


def main():
    parser = argparse.ArgumentParser(description="Check RAG index health.")
    parser.add_argument("--hospital-id", type=int, required=True)
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print(json.dumps(
            get_hospital_index_health(db, args.hospital_id),
            indent=2,
            default=str,
        ))
    finally:
        db.close()


if __name__ == "__main__":
    main()
