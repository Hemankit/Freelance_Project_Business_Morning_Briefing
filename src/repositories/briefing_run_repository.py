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

BriefingRunStatus = Literal[
    "running",
    "completed",
    "failed",
]

VALID_BRIEFING_RUN_STATUSES: set[str] = {
    "running",
    "completed",
    "failed",
}


class BriefingRunRepositoryError(RuntimeError):
    """Base error for briefing run persistence operations."""


class BriefingRunNotFoundError(BriefingRunRepositoryError):
    """Raised when a requested briefing run does not exist."""


@dataclass(frozen=True)
class BriefingRun:
    id: str
    client_id: str
    started_at: str
    completed_at: str | None
    status: BriefingRunStatus
    calendar_event_count: int
    stripe_event_count: int
    selected_event_count: int
    email_message_id: str | None
    error_stage: str | None
    error_message: str | None


class BriefingRunRepository:
    """
    Persist and retrieve briefing run history.

    start_run creates one row per run attempt; complete_run/fail_run
    update that same row once the run finishes.
    """

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
            raise BriefingRunRepositoryError(
                "Could not open the briefing run database."
            ) from exc

    def initialize_database(self) -> None:
        """Create the briefing_runs table if necessary."""
        try:
            with self._get_connection() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS briefing_runs (
                        id TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL
                            REFERENCES clients(id)
                            ON DELETE CASCADE,
                        started_at TEXT NOT NULL,
                        completed_at TEXT,
                        status TEXT NOT NULL
                            CHECK (
                                status IN (
                                    'running',
                                    'completed',
                                    'failed'
                                )
                            ),
                        calendar_event_count INTEGER NOT NULL,
                        stripe_event_count INTEGER NOT NULL,
                        selected_event_count INTEGER NOT NULL,
                        email_message_id TEXT,
                        error_stage TEXT,
                        error_message TEXT
                    )
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                        idx_briefing_runs_client_started_at
                    ON briefing_runs(client_id, started_at)
                    """
                )
        except sqlite3.Error as exc:
            raise BriefingRunRepositoryError(
                "Briefing run database could not be initialized."
            ) from exc

        try:
            restrict_permissions(self.database_path)
        except DatabaseError as exc:
            raise BriefingRunRepositoryError(
                "Could not restrict briefing run database permissions."
            ) from exc

    def start_run(
        self,
        *,
        client_id: str,
    ) -> BriefingRun:
        """Create a new run in the 'running' state."""
        normalized_client_id = self._validate_nonempty_string(
            client_id, "Client ID"
        )

        record = BriefingRun(
            id=str(uuid4()),
            client_id=normalized_client_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=None,
            status="running",
            calendar_event_count=0,
            stripe_event_count=0,
            selected_event_count=0,
            email_message_id=None,
            error_stage=None,
            error_message=None,
        )

        try:
            with self._get_connection() as connection:
                connection.execute(
                    """
                    INSERT INTO briefing_runs (
                        id,
                        client_id,
                        started_at,
                        completed_at,
                        status,
                        calendar_event_count,
                        stripe_event_count,
                        selected_event_count,
                        email_message_id,
                        error_stage,
                        error_message
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.id,
                        record.client_id,
                        record.started_at,
                        record.completed_at,
                        record.status,
                        record.calendar_event_count,
                        record.stripe_event_count,
                        record.selected_event_count,
                        record.email_message_id,
                        record.error_stage,
                        record.error_message,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise BriefingRunRepositoryError(
                "Briefing run references a client that does not exist."
            ) from exc
        except sqlite3.Error as exc:
            raise BriefingRunRepositoryError(
                "Briefing run could not be created."
            ) from exc

        return record

    def complete_run(
        self,
        *,
        run_id: str,
        calendar_event_count: int,
        stripe_event_count: int,
        selected_event_count: int,
        email_message_id: str | None = None,
    ) -> BriefingRun:
        """Mark a run as completed with its final event counts."""
        return self._finish_run(
            run_id=run_id,
            status="completed",
            calendar_event_count=calendar_event_count,
            stripe_event_count=stripe_event_count,
            selected_event_count=selected_event_count,
            email_message_id=email_message_id,
            error_stage=None,
            error_message=None,
        )

    def fail_run(
        self,
        *,
        run_id: str,
        error_stage: str,
        error_message: str,
        calendar_event_count: int = 0,
        stripe_event_count: int = 0,
        selected_event_count: int = 0,
    ) -> BriefingRun:
        """Mark a run as failed with diagnostic information."""
        normalized_error_stage = self._validate_nonempty_string(
            error_stage, "Error stage"
        )
        normalized_error_message = self._validate_nonempty_string(
            error_message, "Error message"
        )

        return self._finish_run(
            run_id=run_id,
            status="failed",
            calendar_event_count=calendar_event_count,
            stripe_event_count=stripe_event_count,
            selected_event_count=selected_event_count,
            email_message_id=None,
            error_stage=normalized_error_stage,
            error_message=normalized_error_message,
        )

    def _finish_run(
        self,
        *,
        run_id: str,
        status: BriefingRunStatus,
        calendar_event_count: int,
        stripe_event_count: int,
        selected_event_count: int,
        email_message_id: str | None,
        error_stage: str | None,
        error_message: str | None,
    ) -> BriefingRun:
        normalized_run_id = self._validate_nonempty_string(
            run_id, "Run ID"
        )
        normalized_calendar_count = self._validate_non_negative_int(
            calendar_event_count, "Calendar event count"
        )
        normalized_stripe_count = self._validate_non_negative_int(
            stripe_event_count, "Stripe event count"
        )
        normalized_selected_count = self._validate_non_negative_int(
            selected_event_count, "Selected event count"
        )

        completed_at = datetime.now(timezone.utc).isoformat()

        try:
            with self._get_connection() as connection:
                cursor = connection.execute(
                    """
                    UPDATE briefing_runs
                    SET
                        status = ?,
                        completed_at = ?,
                        calendar_event_count = ?,
                        stripe_event_count = ?,
                        selected_event_count = ?,
                        email_message_id = ?,
                        error_stage = ?,
                        error_message = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        completed_at,
                        normalized_calendar_count,
                        normalized_stripe_count,
                        normalized_selected_count,
                        email_message_id,
                        error_stage,
                        error_message,
                        normalized_run_id,
                    ),
                )
        except sqlite3.Error as exc:
            raise BriefingRunRepositoryError(
                "Briefing run could not be updated."
            ) from exc

        if cursor.rowcount == 0:
            raise BriefingRunNotFoundError(
                f"No briefing run found for ID '{normalized_run_id}'."
            )

        run = self.get_run(run_id=normalized_run_id)
        assert run is not None

        return run

    def get_run(
        self,
        *,
        run_id: str,
    ) -> BriefingRun | None:
        normalized_run_id = self._validate_nonempty_string(
            run_id, "Run ID"
        )

        try:
            with self._get_connection() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM briefing_runs WHERE id = ?
                    """,
                    (normalized_run_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise BriefingRunRepositoryError(
                "Briefing run could not be loaded."
            ) from exc

        if row is None:
            return None

        return self._row_to_run(row)

    def get_latest_run_for_client(
        self,
        *,
        client_id: str,
    ) -> BriefingRun | None:
        normalized_client_id = self._validate_nonempty_string(
            client_id, "Client ID"
        )

        try:
            with self._get_connection() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM briefing_runs
                    WHERE client_id = ?
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (normalized_client_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise BriefingRunRepositoryError(
                "Briefing run could not be loaded."
            ) from exc

        if row is None:
            return None

        return self._row_to_run(row)

    def list_runs_for_client(
        self,
        *,
        client_id: str,
        limit: int = 50,
    ) -> list[BriefingRun]:
        normalized_client_id = self._validate_nonempty_string(
            client_id, "Client ID"
        )

        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit <= 0
        ):
            raise ValueError(
                "Limit must be a positive integer."
            )

        try:
            with self._get_connection() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM briefing_runs
                    WHERE client_id = ?
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (normalized_client_id, limit),
                ).fetchall()
        except sqlite3.Error as exc:
            raise BriefingRunRepositoryError(
                "Briefing runs could not be listed."
            ) from exc

        return [self._row_to_run(row) for row in rows]

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> BriefingRun:
        return BriefingRun(
            id=row["id"],
            client_id=row["client_id"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            status=row["status"],
            calendar_event_count=row["calendar_event_count"],
            stripe_event_count=row["stripe_event_count"],
            selected_event_count=row["selected_event_count"],
            email_message_id=row["email_message_id"],
            error_stage=row["error_stage"],
            error_message=row["error_message"],
        )

    @staticmethod
    def _validate_nonempty_string(
        value: str,
        field_name: str,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(
                f"{field_name} must be a string."
            )

        normalized = value.strip()

        if not normalized:
            raise ValueError(
                f"{field_name} must not be empty."
            )

        return normalized

    @staticmethod
    def _validate_non_negative_int(
        value: int,
        field_name: str,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(
                f"{field_name} must be an integer."
            )

        if value < 0:
            raise ValueError(
                f"{field_name} must not be negative."
            )

        return value