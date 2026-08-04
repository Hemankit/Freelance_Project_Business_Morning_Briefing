import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.storage.database import (
    DATABASE_PATH,
    DatabaseError,
    get_connection as get_shared_connection,
    restrict_permissions,
)

VALID_ENABLED_SOURCES: set[str] = {
    "google_calendar",
    "stripe",
}


class ConfigurationRepositoryError(RuntimeError):
    """Base error for rules configuration persistence operations."""


@dataclass(frozen=True)
class RulesConfiguration:
    client_id: str
    recipient_email: str
    timezone: str
    delivery_time: str
    lookback_hours: int
    rules_json: dict[str, Any]
    enabled_sources: list[str]
    updated_at: str


class ConfigurationRepository:
    """
    Persist and retrieve one rules configuration per client.

    There is at most one configuration row per client_id.
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
            raise ConfigurationRepositoryError(
                "Could not open the configuration database."
            ) from exc

    def initialize_database(self) -> None:
        """Create the rules_configurations table if necessary."""
        try:
            with self._get_connection() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rules_configurations (
                        client_id TEXT PRIMARY KEY
                            REFERENCES clients(id)
                            ON DELETE CASCADE,
                        recipient_email TEXT NOT NULL,
                        timezone TEXT NOT NULL,
                        delivery_time TEXT NOT NULL,
                        lookback_hours INTEGER NOT NULL,
                        rules_json TEXT NOT NULL,
                        enabled_sources TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
        except sqlite3.Error as exc:
            raise ConfigurationRepositoryError(
                "Configuration database could not be initialized."
            ) from exc

        try:
            restrict_permissions(self.database_path)
        except DatabaseError as exc:
            raise ConfigurationRepositoryError(
                "Could not restrict configuration database permissions."
            ) from exc

    def save_configuration(
        self,
        *,
        client_id: str,
        recipient_email: str,
        timezone: str,
        delivery_time: str,
        lookback_hours: int,
        rules_json: dict[str, Any],
        enabled_sources: list[str],
    ) -> RulesConfiguration:
        """Create or replace the rules configuration for a client."""
        normalized_client_id = self._validate_client_id(
            client_id
        )
        normalized_email = self._validate_recipient_email(
            recipient_email
        )
        normalized_timezone = self._validate_timezone(
            timezone
        )
        normalized_delivery_time = self._validate_delivery_time(
            delivery_time
        )
        normalized_lookback_hours = self._validate_lookback_hours(
            lookback_hours
        )
        normalized_rules_json = self._validate_rules_json(
            rules_json
        )
        normalized_enabled_sources = self._validate_enabled_sources(
            enabled_sources
        )

        now = datetime.now(dt_timezone.utc).isoformat()

        try:
            with self._get_connection() as connection:
                connection.execute(
                    """
                    INSERT INTO rules_configurations (
                        client_id,
                        recipient_email,
                        timezone,
                        delivery_time,
                        lookback_hours,
                        rules_json,
                        enabled_sources,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(client_id) DO UPDATE SET
                        recipient_email = excluded.recipient_email,
                        timezone = excluded.timezone,
                        delivery_time = excluded.delivery_time,
                        lookback_hours = excluded.lookback_hours,
                        rules_json = excluded.rules_json,
                        enabled_sources = excluded.enabled_sources,
                        updated_at = excluded.updated_at
                    """,
                    (
                        normalized_client_id,
                        normalized_email,
                        normalized_timezone,
                        normalized_delivery_time,
                        normalized_lookback_hours,
                        json.dumps(normalized_rules_json),
                        json.dumps(normalized_enabled_sources),
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ConfigurationRepositoryError(
                "Configuration references a client that "
                "does not exist."
            ) from exc
        except sqlite3.Error as exc:
            raise ConfigurationRepositoryError(
                "Configuration could not be saved."
            ) from exc

        return RulesConfiguration(
            client_id=normalized_client_id,
            recipient_email=normalized_email,
            timezone=normalized_timezone,
            delivery_time=normalized_delivery_time,
            lookback_hours=normalized_lookback_hours,
            rules_json=normalized_rules_json,
            enabled_sources=normalized_enabled_sources,
            updated_at=now,
        )

    def get_configuration(
        self,
        *,
        client_id: str,
    ) -> RulesConfiguration | None:
        """Return a client's configuration, or None when it does not exist."""
        normalized_client_id = self._validate_client_id(
            client_id
        )

        try:
            with self._get_connection() as connection:
                row = connection.execute(
                    """
                    SELECT
                        client_id,
                        recipient_email,
                        timezone,
                        delivery_time,
                        lookback_hours,
                        rules_json,
                        enabled_sources,
                        updated_at
                    FROM rules_configurations
                    WHERE client_id = ?
                    """,
                    (normalized_client_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise ConfigurationRepositoryError(
                "Configuration could not be loaded."
            ) from exc

        if row is None:
            return None

        return self._row_to_configuration(row)

    def delete_configuration(
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
                    DELETE FROM rules_configurations
                    WHERE client_id = ?
                    """,
                    (normalized_client_id,),
                )
                return cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise ConfigurationRepositoryError(
                "Configuration could not be deleted."
            ) from exc

    @staticmethod
    def _row_to_configuration(
        row: sqlite3.Row,
    ) -> RulesConfiguration:
        return RulesConfiguration(
            client_id=row["client_id"],
            recipient_email=row["recipient_email"],
            timezone=row["timezone"],
            delivery_time=row["delivery_time"],
            lookback_hours=row["lookback_hours"],
            rules_json=json.loads(row["rules_json"]),
            enabled_sources=json.loads(row["enabled_sources"]),
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
    def _validate_recipient_email(
        recipient_email: str,
    ) -> str:
        if not isinstance(recipient_email, str):
            raise TypeError(
                "Recipient email must be a string."
            )

        normalized = recipient_email.strip().lower()

        if (
            not normalized
            or "@" not in normalized
            or normalized.startswith("@")
            or normalized.endswith("@")
        ):
            raise ValueError(
                "Recipient email is invalid."
            )

        return normalized

    @staticmethod
    def _validate_timezone(timezone: str) -> str:
        if not isinstance(timezone, str) or not timezone.strip():
            raise ValueError(
                "Timezone must be a non-empty string."
            )

        normalized = timezone.strip()

        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"'{normalized}' is not a known IANA timezone."
            ) from exc

        return normalized

    @staticmethod
    def _validate_delivery_time(delivery_time: str) -> str:
        if not isinstance(delivery_time, str):
            raise TypeError(
                "Delivery time must be a string."
            )

        normalized = delivery_time.strip()

        try:
            datetime.strptime(normalized, "%H:%M")
        except ValueError as exc:
            raise ValueError(
                "Delivery time must use 24-hour 'HH:MM' format."
            ) from exc

        return normalized

    @staticmethod
    def _validate_lookback_hours(lookback_hours: int) -> int:
        if (
            not isinstance(lookback_hours, int)
            or isinstance(lookback_hours, bool)
        ):
            raise TypeError(
                "Lookback hours must be an integer."
            )

        if lookback_hours <= 0:
            raise ValueError(
                "Lookback hours must be positive."
            )

        return lookback_hours

    @staticmethod
    def _validate_rules_json(
        rules_json: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(rules_json, dict):
            raise TypeError(
                "Rules JSON must be a dictionary."
            )

        try:
            json.dumps(rules_json)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Rules JSON must be JSON serializable."
            ) from exc

        return rules_json

    @staticmethod
    def _validate_enabled_sources(
        enabled_sources: list[str],
    ) -> list[str]:
        if not isinstance(enabled_sources, list) or not enabled_sources:
            raise ValueError(
                "Enabled sources must be a non-empty list."
            )

        normalized = sorted(set(enabled_sources))

        invalid = [
            source
            for source in normalized
            if source not in VALID_ENABLED_SOURCES
        ]

        if invalid:
            allowed = ", ".join(sorted(VALID_ENABLED_SOURCES))
            raise ValueError(
                f"Invalid enabled sources {invalid}. "
                f"Allowed sources: {allowed}."
            )

        return normalized
