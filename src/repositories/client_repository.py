import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from src.storage.database import (
    DATABASE_PATH,
    DatabaseError,
    get_connection as get_shared_connection,
    restrict_permissions,
)


ClientStatus = Literal[
    "pending_setup",
    "active",
    "paused",
]

VALID_CLIENT_STATUSES: set[str] = {
    "pending_setup",
    "active",
    "paused",
}


class ClientRepositoryError(RuntimeError):
    """Base error for client repository operations."""


class ClientNotFoundError(ClientRepositoryError):
    """Raised when a requested client does not exist."""


@dataclass(frozen=True)
class ClientConfiguration:
    id: str
    status: ClientStatus
    created_at: str
    updated_at: str


class ClientRepository:
    """Persist and retrieve basic client configuration records."""

    def __init__(
        self,
        database_path: Path = DATABASE_PATH,
    ) -> None:
        self.database_path = database_path
        self.initialize_database()

    def _get_connection(self) -> sqlite3.Connection:
        try:
            return get_shared_connection(self.database_path)
        except DatabaseError as exc:
            raise ClientRepositoryError(
                "Could not open the client database."
            ) from exc

    def initialize_database(self) -> None:
        """Create the clients table if necessary."""
        try:
            with self._get_connection() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS clients (
                        id TEXT PRIMARY KEY,
                        status TEXT NOT NULL
                            CHECK (
                                status IN (
                                    'pending_setup',
                                    'active',
                                    'paused'
                                )
                            ),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
        except sqlite3.Error as exc:
            raise ClientRepositoryError(
                "Client database could not be initialized."
            ) from exc

        try:
            restrict_permissions(self.database_path)
        except DatabaseError as exc:
            raise ClientRepositoryError(
                "Could not restrict client database permissions."
            ) from exc

    def create_client(
        self,
        *,
        client_id: str | None = None,
        status: ClientStatus = "pending_setup",
    ) -> ClientConfiguration:
        """
        Create a new client.

        New clients default to pending_setup.
        """
        normalized_status = self._validate_status(status)

        resolved_client_id = (
            client_id.strip()
            if client_id and client_id.strip()
            else str(uuid4())
        )

        now = datetime.now(timezone.utc).isoformat()

        try:
            with self._get_connection() as connection:
                connection.execute(
                    """
                    INSERT INTO clients (
                        id,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        resolved_client_id,
                        normalized_status,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ClientRepositoryError(
                "A client with this ID already exists."
            ) from exc
        except sqlite3.Error as exc:
            raise ClientRepositoryError(
                "Client could not be created."
            ) from exc

        return ClientConfiguration(
            id=resolved_client_id,
            status=normalized_status,
            created_at=now,
            updated_at=now,
        )

    def get_client(
        self,
        *,
        client_id: str,
    ) -> ClientConfiguration | None:
        """Return a client, or None when it does not exist."""
        normalized_client_id = self._validate_client_id(
            client_id
        )

        try:
            with self._get_connection() as connection:
                row = connection.execute(
                    """
                    SELECT
                        id,
                        status,
                        created_at,
                        updated_at
                    FROM clients
                    WHERE id = ?
                    """,
                    (normalized_client_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise ClientRepositoryError(
                "Client could not be loaded."
            ) from exc

        if row is None:
            return None

        return self._row_to_client(row)

    def list_clients(
        self,
        *,
        status: ClientStatus | None = None,
    ) -> list[ClientConfiguration]:
        parameters: tuple[str, ...] = ()

        query = """
            SELECT
                id,
                status,
                created_at,
                updated_at
            FROM clients
        """

        if status is not None:
            normalized_status = self._validate_status(status)
            query += " WHERE status = ?"
            parameters = (normalized_status,)

        query += " ORDER BY created_at ASC"

        try:
            with self._get_connection() as connection:
                rows = connection.execute(
                    query,
                    parameters,
                ).fetchall()
        except sqlite3.Error as exc:
            raise ClientRepositoryError(
                "Clients could not be listed."
            ) from exc

        return [
            self._row_to_client(row)
            for row in rows
        ]

    def update_client(
        self,
        *,
        client_id: str,
        status: ClientStatus | None = None,
    ) -> ClientConfiguration:
        """
        Update selected client fields.

        Fields passed as None remain unchanged.
        """
        normalized_client_id = self._validate_client_id(
            client_id
        )

        current = self.get_client(
            client_id=normalized_client_id
        )

        if current is None:
            raise ClientNotFoundError(
                f"No client found for ID "
                f"'{normalized_client_id}'."
            )

        updated_status = (
            self._validate_status(status)
            if status is not None
            else current.status
        )

        now = datetime.now(timezone.utc).isoformat()

        try:
            with self._get_connection() as connection:
                connection.execute(
                    """
                    UPDATE clients
                    SET
                        status = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        updated_status,
                        now,
                        normalized_client_id,
                    ),
                )
        except sqlite3.Error as exc:
            raise ClientRepositoryError(
                "Client could not be updated."
            ) from exc

        return ClientConfiguration(
            id=current.id,
            status=updated_status,
            created_at=current.created_at,
            updated_at=now,
        )

    def set_client_status(
        self,
        *,
        client_id: str,
        status: ClientStatus,
    ) -> ClientConfiguration:
        return self.update_client(
            client_id=client_id,
            status=status,
        )

    def delete_client(
        self,
        *,
        client_id: str,
    ) -> bool:
        normalized_client_id = self._validate_client_id(
            client_id
        )

        try:
            with self._get_connection() as connection:
                cursor = connection.execute(
                    """
                    DELETE FROM clients
                    WHERE id = ?
                    """,
                    (normalized_client_id,),
                )
                return cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise ClientRepositoryError(
                "Client could not be deleted."
            ) from exc

    @staticmethod
    def _row_to_client(
        row: sqlite3.Row,
    ) -> ClientConfiguration:
        return ClientConfiguration(
            id=row["id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _validate_client_id(client_id: str) -> str:
        if not isinstance(client_id, str):
            raise TypeError(
                "Client ID must be a string."
            )

        normalized = client_id.strip()

        if not normalized:
            raise ValueError(
                "Client ID must not be empty."
            )

        return normalized

    @staticmethod
    def _validate_status(
        status: str,
    ) -> ClientStatus:
        if status not in VALID_CLIENT_STATUSES:
            allowed = ", ".join(
                sorted(VALID_CLIENT_STATUSES)
            )
            raise ValueError(
                f"Invalid client status '{status}'. "
                f"Allowed statuses: {allowed}."
            )

        return status  # type: ignore[return-value]
    
     