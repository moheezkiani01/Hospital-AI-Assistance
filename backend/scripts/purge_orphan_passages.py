"""One-off cleanup: delete RAG passages whose source document no longer exists.

Older versions of the app left a document's passages behind when the document was
deleted, so the chatbot could keep quoting a file the admin had removed.

Run from the backend/ folder:   python scripts/purge_orphan_passages.py [--hospital-id 1]
(New deployments do not need this: ensure_hospital_index() now purges orphans itself.)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.base import Base  # noqa: E402
from app.db.database import SessionLocal, engine  # noqa: E402
from app.services import rag_index_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hospital-id", type=int, default=None, help="limit to one hospital (default: all)")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        removed = rag_index_service.purge_orphan_passages(db, args.hospital_id)
        print(f"Removed {removed} orphaned passage(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
