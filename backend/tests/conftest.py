import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Importing app.db.base (rather than just base_class) pulls in every model's
# import, registering all tables onto Base.metadata -- so the in-memory test
# DB mirrors the real schema, not just the one table a given test happens to
# touch directly.
from app.db.base import Base


@pytest.fixture()
def db_session():
    """Fresh, fully isolated in-memory SQLite DB per test. Never touches the
    real hospital_ai.db."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()
