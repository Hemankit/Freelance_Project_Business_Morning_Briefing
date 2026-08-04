import json
import os
import sqlite3
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from src.storage.database import (
    DatabaseError,
    get_connection as get_shared_connection,
    restrict_permissions,
)


class CredentialStoreError(RuntimeError):
    """Base error for credential storage operations."""


class CredentialNotFoundError(CredentialStoreError):
    """Raised when requested credentials do not exist."""


class CredentialDecryptionError(CredentialStoreError):
    """Raised when stored credentials cannot be decrypted."""


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    """
    Load the stable encryption key from the environment.

    Generate it once with:
        Fernet.generate_key().decode()

    Never store the key in SQLite or commit it to Git.
    """
    encryption_key = os.getenv(
        "CREDENTIALS_ENCRYPTION_KEY"
    )

    if not encryption_key:
        raise CredentialStoreError(
            "CREDENTIALS_ENCRYPTION_KEY is not configured."
        )

    try:
        return Fernet(encryption_key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise CredentialStoreError(
            "CREDENTIALS_ENCRYPTION_KEY is invalid."
        ) from exc


def get_connection() -> sqlite3.Connection:
    try:
        return get_shared_connection()
    except DatabaseError as exc:
        raise CredentialStoreError(
            "Could not open the credential database."
        ) from exc


def initialize_database() -> None:
    """Create the credentials table if necessary."""
    try:
        with get_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS credentials (
                    credential_key TEXT PRIMARY KEY,
                    encrypted_value BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
    except sqlite3.Error as exc:
        raise CredentialStoreError(
            "Credential database could not be initialized."
        ) from exc

    try:
        restrict_permissions()
    except DatabaseError as exc:
        raise CredentialStoreError(
            "Could not restrict credential database permissions."
        ) from exc


def encrypt_credentials(
    credentials: dict[str, Any],
) -> bytes:
    if not isinstance(credentials, dict) or not credentials:
        raise ValueError(
            "Credentials must be a non-empty dictionary."
        )

    try:
        serialized = json.dumps(
            credentials,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CredentialStoreError(
            "Credentials are not JSON serializable."
        ) from exc

    return get_fernet().encrypt(serialized)


def decrypt_credentials(
    encrypted_value: bytes,
) -> dict[str, Any]:
    if isinstance(encrypted_value, memoryview):
        encrypted_value = encrypted_value.tobytes()

    if not isinstance(encrypted_value, bytes):
        raise CredentialDecryptionError(
            "Stored credential data has an invalid type."
        )

    try:
        serialized = get_fernet().decrypt(
            encrypted_value
        )
        result = json.loads(
            serialized.decode("utf-8")
        )
    except (
        InvalidToken,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise CredentialDecryptionError(
            "Stored credentials could not be decrypted."
        ) from exc

    if not isinstance(result, dict):
        raise CredentialDecryptionError(
            "Stored credential data has an invalid format."
        )

    return result


def save_credentials(
    credential_key: str,
    credentials: dict[str, Any],
) -> None:
    """Encrypt and insert or update one credential record."""
    if not credential_key or not credential_key.strip():
        raise ValueError(
            "Credential key must not be empty."
        )

    initialize_database()

    encrypted_value = encrypt_credentials(credentials)
    now = datetime.now(timezone.utc).isoformat()

    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO credentials (
                    credential_key,
                    encrypted_value,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(credential_key) DO UPDATE SET
                    encrypted_value = excluded.encrypted_value,
                    updated_at = excluded.updated_at
                """,
                (
                    credential_key,
                    encrypted_value,
                    now,
                    now,
                ),
            )
    except sqlite3.Error as exc:
        raise CredentialStoreError(
            "Credentials could not be saved."
        ) from exc


def load_credentials(
    credential_key: str,
) -> dict[str, Any]:
    """Load and decrypt one credential record."""
    if not credential_key or not credential_key.strip():
        raise ValueError(
            "Credential key must not be empty."
        )

    initialize_database()

    try:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT encrypted_value
                FROM credentials
                WHERE credential_key = ?
                """,
                (credential_key,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise CredentialStoreError(
            "Credentials could not be loaded."
        ) from exc

    if row is None:
        raise CredentialNotFoundError(
            f"No credentials stored for key "
            f"'{credential_key}'."
        )

    return decrypt_credentials(row["encrypted_value"])


def credentials_exist(
    credential_key: str,
) -> bool:
    if not credential_key or not credential_key.strip():
        raise ValueError(
            "Credential key must not be empty."
        )

    initialize_database()

    try:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM credentials
                WHERE credential_key = ?
                """,
                (credential_key,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise CredentialStoreError(
            "Credential existence could not be checked."
        ) from exc

    return row is not None


def delete_credentials(
    credential_key: str,
) -> bool:
    if not credential_key or not credential_key.strip():
        raise ValueError(
            "Credential key must not be empty."
        )

    initialize_database()

    try:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM credentials
                WHERE credential_key = ?
                """,
                (credential_key,),
            )
            return cursor.rowcount > 0
    except sqlite3.Error as exc:
        raise CredentialStoreError(
            "Credentials could not be deleted."
        ) from exc