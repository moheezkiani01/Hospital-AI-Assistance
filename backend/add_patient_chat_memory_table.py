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
                CREATE TABLE IF NOT EXISTS patient_chat_memories (
                    id INTEGER PRIMARY KEY,
                    hospital_id INTEGER NOT NULL,
                    session_id VARCHAR(150) NOT NULL,
                    phone_number VARCHAR(50),
                    patient_name VARCHAR(150),
                    preferred_language VARCHAR(50),
                    last_appointment_summary TEXT,
                    last_tests_summary TEXT,
                    saved_information TEXT,
                    memory_summary TEXT,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(hospital_id) REFERENCES hospitals(id),
                    UNIQUE(hospital_id, session_id)
                )
                """
            )
        )

        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_patient_chat_memories_hospital_id "
                "ON patient_chat_memories(hospital_id)"
            )
        )

        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_patient_chat_memories_session_id "
                "ON patient_chat_memories(session_id)"
            )
        )

        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_patient_chat_memories_phone_number "
                "ON patient_chat_memories(phone_number)"
            )
        )

        connection.commit()

    print("patient_chat_memories table is ready.")


if __name__ == "__main__":
    main()