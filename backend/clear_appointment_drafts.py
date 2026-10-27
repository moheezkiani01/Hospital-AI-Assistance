from sqlalchemy import create_engine, text
from app.core.config import settings


def get_database_url():
    database_url = getattr(settings, "DATABASE_URL", None)

    if database_url:
        return database_url

    database_url = getattr(settings, "SQLALCHEMY_DATABASE_URL", None)

    if database_url:
        return database_url

    return "sqlite:///./hospital_ai.db"


def main():
    database_url = get_database_url()
    connect_args = {}

    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    engine = create_engine(database_url, connect_args=connect_args)

    with engine.connect() as connection:
        connection.execute(
            text("UPDATE appointment_drafts SET status='cancelled' WHERE status='collecting'")
        )
        connection.commit()

    print("Old active appointment drafts cleared.")


if __name__ == "__main__":
    main()