import argparse

from app.db.base import Base
from app.db.database import SessionLocal, engine
from app.models.document_chunk import DocumentChunk
from app.services.rag_index_service import rebuild_hospital_index


def main():
    parser = argparse.ArgumentParser(description="Rebuild semantic RAG passage index.")
    parser.add_argument("--hospital-id", type=int, default=None)
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if args.hospital_id is not None:
            hospital_ids = [args.hospital_id]
        else:
            hospital_ids = [
                row[0]
                for row in (
                    db.query(DocumentChunk.hospital_id)
                    .distinct()
                    .order_by(DocumentChunk.hospital_id.asc())
                    .all()
                )
            ]

        if not hospital_ids:
            print("No hospital document chunks found.")
            return

        for hospital_id in hospital_ids:
            print(f"Rebuilding RAG index for hospital {hospital_id} ...")
            stats = rebuild_hospital_index(db, hospital_id)
            print(stats)
    finally:
        db.close()


if __name__ == "__main__":
    main()
