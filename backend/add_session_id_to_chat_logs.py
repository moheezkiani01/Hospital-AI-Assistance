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
        columns = connection.execute(text("PRAGMA table_info(chat_logs)")).fetchall()
        column_names = [column[1] for column in columns]

        if "session_id" not in column_names:
            connection.execute(
                text("ALTER TABLE chat_logs ADD COLUMN session_id VARCHAR(150) DEFAULT 'default'")
            )
            connection.commit()
            print("Added session_id column to chat_logs table.")
        else:
            print("session_id column already exists.")

        connection.execute(
            text("UPDATE chat_logs SET session_id = 'default' WHERE session_id IS NULL")
        )

        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_chat_logs_session_id ON chat_logs(session_id)")
        )

        connection.commit()

        print("Chat logs session_id migration completed.")


if __name__ == "__main__":
    main()