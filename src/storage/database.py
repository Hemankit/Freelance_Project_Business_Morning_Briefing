"""Shared SQLite connection handling for all repositories.

All application tables live in one database file. Centralizing the
connection logic here means the eventual move to a server-based
database (e.g. Postgres) only requires changing this module.
"""

import os
import sqlite3
from pathlib import Path

DATABASE_PATH = Path(
    os.getenv(
        "DATABASE_PATH",
        "data/app.db",
    )
)


class DatabaseError(RuntimeError):
    """Raised when the shared database cannot be opened or configured."""


def get_connection(
    database_path: Path = DATABASE_PATH,
) -> sqlite3.Connection:
    """
    Open a connection to the shared application database.

    isolation_level=None (autocommit) lets callers opt into explicit
    BEGIN IMMEDIATE / commit / rollback when they need multi-statement
    transactions.
    """
    try:
        database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = sqlite3.connect(
            database_path,
            timeout=10.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")

        return connection
    except (OSError, sqlite3.Error) as exc:
        raise DatabaseError(
            "Could not open the application database."
        ) from exc


def restrict_permissions(
    database_path: Path = DATABASE_PATH,
) -> None:
    """Restrict the database file to owner read/write on POSIX systems."""
    if os.name != "nt" and database_path.exists():
        try:
            database_path.chmod(0o600)
        except OSError as exc:
            raise DatabaseError(
                "Could not restrict application database permissions."
            ) from exc
