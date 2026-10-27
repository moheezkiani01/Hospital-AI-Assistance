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
            text(
                """
                CREATE TABLE IF NOT EXISTS appointment_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hospital_id INTEGER NOT NULL,
                    session_id VARCHAR(150) NOT NULL,
                    source VARCHAR(50) DEFAULT 'website',
                    whatsapp_number VARCHAR(50),
                    doctor_id INTEGER,
                    doctor_name_text VARCHAR(200),
                    appointment_date DATE,
                    appointment_time TIME,
                    patient_name VARCHAR(200),
                    patient_phone VARCHAR(50),
                    status VARCHAR(50) DEFAULT 'collecting',
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )

        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_appointment_drafts_hospital_id ON appointment_drafts(hospital_id)")
        )

        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_appointment_drafts_session_id ON appointment_drafts(session_id)")
        )

        connection.commit()

    print("appointment_drafts table created successfully.")


if __name__ == "__main__":
    main()