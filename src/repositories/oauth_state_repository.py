import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from src.storage.database import (
    DATABASE_PATH,
    DatabaseError,
    get_connection as get_shared_connection,
    restrict_permissions,
)

OAuthProvider = Literal[
    "google_calendar",
    "stripe",
]

VALID_OAUTH_PROVIDERS: set[str] = {
    "google_calendar",
    "stripe",
}


class OAuthStateRepositoryError(RuntimeError):
    """Base error for OAuth state persistence operations."""


class OAuthStateInvalidError(OAuthStateRepositoryError):
    """Raised when an OAuth state token is invalid or unavailable."""


class OAuthStateExpiredError(OAuthStateInvalidError):
    """Raised when an OAuth state token has expired."""


class OAuthStateProviderMismatchError(OAuthStateInvalidError):
    """Raised when state was created for another provider."""


@dataclass(frozen=True)
class OAuthState:
    state_hash: str
    client_id: str
    provider: OAuthProvider
    setup_session_id: str
    expires_at: str
    created_at: str


@dataclass(frozen=True)
class CreatedOAuthState:
    """
    Result returned when beginning OAuth.

    raw_state is sent to the OAuth provider.
    record is the persisted metadata.
    """

    raw_state: str
    record: OAuthState


class OAuthStateRepository:
    """
    Persist short-lived, provider-bound, single-use OAuth state.

    The raw state token is never stored. Only its SHA-256 hash is
    persisted.
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
            raise OAuthStateRepositoryError(
                "Could not open the OAuth state database."
            ) from exc

    def initialize_database(self) -> None:
        try:
            with self._get_connection() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS oauth_states (
                        state_hash TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL,
                        provider TEXT NOT NULL
                            CHECK (
                                provider IN (
                                    'google_calendar',
                                    'stripe'
                                )
                            ),
                        setup_session_id TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                        idx_oauth_states_expires_at
                    ON oauth_states(expires_at)
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                        idx_oauth_states_client_provider
                    ON oauth_states(
                        client_id,
                        provider
                    )
                    """
                )
        except sqlite3.Error as exc:
            raise OAuthStateRepositoryError(
                "OAuth state database could not be initialized."
            ) from exc

        try:
            restrict_permissions(self.database_path)
        except DatabaseError as exc:
            raise OAuthStateRepositoryError(
                "Could not restrict OAuth state "
                "database permissions."
            ) from exc

    def create_state(
        self,
        *,
        client_id: str,
        provider: OAuthProvider,
        setup_session_id: str,
        lifetime: timedelta = timedelta(minutes=10),
    ) -> CreatedOAuthState:
        """
        Create and persist a new OAuth state token.

        The returned raw_state should be placed in the provider's
        authorization URL.
        """
        normalized_client_id = self._validate_nonempty_string(
            client_id,
            "Client ID",
        )
        normalized_provider = self._validate_provider(
            provider
        )
        normalized_session_id = self._validate_nonempty_string(
            setup_session_id,
            "Setup session ID",
        )

        if lifetime <= timedelta(0):
            raise ValueError(
                "OAuth state lifetime must be positive."
            )

        created_at = datetime.now(timezone.utc)
        expires_at = created_at + lifetime

        raw_state = secrets.token_urlsafe(32)
        state_hash = self._hash_state(raw_state)

        record = OAuthState(
            state_hash=state_hash,
            client_id=normalized_client_id,
            provider=normalized_provider,
            setup_session_id=normalized_session_id,
            expires_at=expires_at.isoformat(),
            created_at=created_at.isoformat(),
        )

        try:
            with self._get_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")

                connection.execute(
                    """
                    INSERT INTO oauth_states (
                        state_hash,
                        client_id,
                        provider,
                        setup_session_id,
                        expires_at,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.state_hash,
                        record.client_id,
                        record.provider,
                        record.setup_session_id,
                        record.expires_at,
                        record.created_at,
                    ),
                )

                connection.commit()
        except sqlite3.Error as exc:
            raise OAuthStateRepositoryError(
                "OAuth state could not be created."
            ) from exc

        return CreatedOAuthState(
            raw_state=raw_state,
            record=record,
        )

    def consume_state(
        self,
        *,
        raw_state: str,
        provider: OAuthProvider,
    ) -> OAuthState:
        """
        Validate and atomically consume one OAuth state token.

        A successfully consumed token cannot be used again.
        """
        normalized_raw_state = self._validate_nonempty_string(
            raw_state,
            "OAuth state",
        )
        normalized_provider = self._validate_provider(
            provider
        )
        state_hash = self._hash_state(
            normalized_raw_state
        )

        connection = self._get_connection()

        try:
            # BEGIN IMMEDIATE ensures that two workers cannot both
            # successfully consume the same state record.
            connection.execute("BEGIN IMMEDIATE")

            row = connection.execute(
                """
                SELECT
                    state_hash,
                    client_id,
                    provider,
                    setup_session_id,
                    expires_at,
                    created_at
                FROM oauth_states
                WHERE state_hash = ?
                """,
                (state_hash,),
            ).fetchone()

            if row is None:
                connection.rollback()
                raise OAuthStateInvalidError(
                    "OAuth state is invalid or has already been used."
                )

            record = self._row_to_state(row)

            if record.provider != normalized_provider:
                connection.rollback()
                raise OAuthStateProviderMismatchError(
                    "OAuth state was created for a different provider."
                )

            # Delete before returning so successful validation is
            # strictly single-use.
            connection.execute(
                """
                DELETE FROM oauth_states
                WHERE state_hash = ?
                """,
                (state_hash,),
            )

            expires_at = self._parse_timestamp(
                record.expires_at
            )
            now = datetime.now(timezone.utc)

            if expires_at <= now:
                # Commit the deletion so an expired state cannot be
                # repeatedly presented.
                connection.commit()
                raise OAuthStateExpiredError(
                    "OAuth state has expired."
                )

            connection.commit()
            return record

        except OAuthStateInvalidError:
            raise
        except sqlite3.Error as exc:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass

            raise OAuthStateRepositoryError(
                "OAuth state could not be consumed."
            ) from exc
        finally:
            connection.close()

    def delete_states_for_setup_session(
        self,
        *,
        setup_session_id: str,
    ) -> int:
        """
        Invalidate all authorization attempts for a setup session.
        """
        normalized_session_id = self._validate_nonempty_string(
            setup_session_id,
            "Setup session ID",
        )

        try:
            with self._get_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")

                cursor = connection.execute(
                    """
                    DELETE FROM oauth_states
                    WHERE setup_session_id = ?
                    """,
                    (normalized_session_id,),
                )

                deleted_count = cursor.rowcount
                connection.commit()

                return deleted_count
        except sqlite3.Error as exc:
            raise OAuthStateRepositoryError(
                "OAuth states could not be deleted."
            ) from exc

    def delete_states_for_client(
        self,
        *,
        client_id: str,
        provider: OAuthProvider | None = None,
    ) -> int:
        """
        Invalidate pending OAuth attempts for a client.
        """
        normalized_client_id = self._validate_nonempty_string(
            client_id,
            "Client ID",
        )

        try:
            with self._get_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")

                if provider is None:
                    cursor = connection.execute(
                        """
                        DELETE FROM oauth_states
                        WHERE client_id = ?
                        """,
                        (normalized_client_id,),
                    )
                else:
                    normalized_provider = self._validate_provider(
                        provider
                    )

                    cursor = connection.execute(
                        """
                        DELETE FROM oauth_states
                        WHERE client_id = ?
                          AND provider = ?
                        """,
                        (
                            normalized_client_id,
                            normalized_provider,
                        ),
                    )

                deleted_count = cursor.rowcount
                connection.commit()

                return deleted_count
        except sqlite3.Error as exc:
            raise OAuthStateRepositoryError(
                "OAuth states could not be deleted."
            ) from exc

    def delete_expired_states(self) -> int:
        """Remove expired OAuth state records."""
        now = datetime.now(timezone.utc).isoformat()

        try:
            with self._get_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")

                cursor = connection.execute(
                    """
                    DELETE FROM oauth_states
                    WHERE expires_at <= ?
                    """,
                    (now,),
                )

                deleted_count = cursor.rowcount
                connection.commit()

                return deleted_count
        except sqlite3.Error as exc:
            raise OAuthStateRepositoryError(
                "Expired OAuth states could not be deleted."
            ) from exc

    @staticmethod
    def _hash_state(raw_state: str) -> str:
        return hashlib.sha256(
            raw_state.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _row_to_state(
        row: sqlite3.Row,
    ) -> OAuthState:
        return OAuthState(
            state_hash=row["state_hash"],
            client_id=row["client_id"],
            provider=row["provider"],
            setup_session_id=row["setup_session_id"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise OAuthStateRepositoryError(
                "Stored OAuth state has an invalid timestamp."
            ) from exc

        if parsed.tzinfo is None:
            raise OAuthStateRepositoryError(
                "Stored OAuth state timestamp has no timezone."
            )

        return parsed.astimezone(timezone.utc)

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
    def _validate_provider(
        provider: str,
    ) -> OAuthProvider:
        if provider not in VALID_OAUTH_PROVIDERS:
            allowed = ", ".join(
                sorted(VALID_OAUTH_PROVIDERS)
            )
            raise ValueError(
                f"Invalid OAuth provider '{provider}'. "
                f"Allowed providers: {allowed}."
            )

        return provider  # type: ignore[return-value]
