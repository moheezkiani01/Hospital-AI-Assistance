"""Create a consistent, verified backup of a SQLite hospital database.

Usage from backend/: python scripts/backup_sqlite.py --output backups/hospital_ai_backup.sqlite3
Does not overwrite an existing backup or modify the source database.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import quote


def backup_sqlite_file(source: Path, destination: Path) -> Path:
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()

    if not source.is_file():
        raise FileNotFoundError(f"SQLite database not found: {source}")
    if source == destination:
        raise ValueError("The backup destination cannot be the source database")
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".hospital-backup-", suffix=".sqlite3", dir=destination.parent
    )
    os.close(fd)
    temporary_path = Path(temporary)

    try:
        source_uri = "file:" + quote(source.as_posix(), safe="/:") + "?mode=ro"

        # A sqlite3 Connection's `with` block commits a transaction but does
        # NOT close the connection. Windows will refuse to rename/delete an
        # open database file, so both connections must be explicitly closed.
        with closing(sqlite3.connect(source_uri, uri=True, timeout=15)) as original:
            with closing(sqlite3.connect(str(temporary_path), timeout=15)) as copy:
                original.backup(copy)
                result = copy.execute("PRAGMA quick_check").fetchone()
                if not result or result[0] != "ok":
                    raise RuntimeError("Backup failed SQLite integrity verification")

        # Connections are closed before moving the temporary database.
        # Use a new destination name rather than overwriting an older backup.
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite existing backup: {destination}")
        os.rename(temporary_path, destination)
        return destination
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safe backup for a local SQLite hospital database"
    )
    parser.add_argument(
        "--output", required=True, help="New backup file (must not already exist)"
    )
    args = parser.parse_args()

    backend_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_dir))
    from sqlalchemy.engine import make_url
    from app.core.config import settings

    database_url = make_url(settings.DATABASE_URL)
    if (
        not database_url.drivername.startswith("sqlite")
        or not database_url.database
        or database_url.database == ":memory:"
    ):
        parser.error("This utility supports only file-backed SQLite databases")

    source = Path(database_url.database)
    if not source.is_absolute():
        source = backend_dir / source

    destination = Path(args.output)
    if not destination.is_absolute():
        destination = backend_dir / destination

    try:
        result = backup_sqlite_file(source, destination)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Backup failed: {exc}\n")

    print(f"Verified backup created: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
