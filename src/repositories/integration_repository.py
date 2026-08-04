from dataclasses import dataclass
from typing import Any

from src.storage.credentials_store import (
    CredentialNotFoundError,
    delete_credentials,
    load_credentials,
    save_credentials,
)


@dataclass(frozen=True)
class IntegrationConnection:
    client_id: str
    provider: str
    credentials: dict[str, Any]


class IntegrationRepository:
    """Persist and retrieve OAuth integration credentials."""

    GOOGLE_PROVIDER = "google_calendar"
    STRIPE_PROVIDER = "stripe"

    @classmethod
    def _google_key(cls, client_id: str) -> str:
        return f"{cls.GOOGLE_PROVIDER}:{client_id}"

    @classmethod
    def _stripe_key(cls, client_id: str) -> str:
        return f"{cls.STRIPE_PROVIDER}:{client_id}"

    # ------------------------------------------------------------------
    # Google Calendar
    # ------------------------------------------------------------------

    def upsert_google_calendar_connection(
        self,
        *,
        client_id: str,
        credentials: dict[str, Any],
    ) -> None:
        save_credentials(
            self._google_key(client_id),
            credentials,
        )

    def get_google_calendar_connection(
        self,
        *,
        client_id: str,
    ) -> IntegrationConnection | None:
        try:
            credentials = load_credentials(
                self._google_key(client_id)
            )
        except CredentialNotFoundError:
            return None

        return IntegrationConnection(
            client_id=client_id,
            provider=self.GOOGLE_PROVIDER,
            credentials=dict(credentials),
        )

    def delete_google_calendar_connection(
        self,
        *,
        client_id: str,
    ) -> None:
        delete_credentials(self._google_key(client_id))

    # ------------------------------------------------------------------
    # Stripe
    # ------------------------------------------------------------------

    def upsert_stripe_connection(
        self,
        *,
        client_id: str,
        credentials: dict[str, Any],
    ) -> None:
        save_credentials(
            self._stripe_key(client_id),
            credentials,
        )

    def get_stripe_connection(
        self,
        *,
        client_id: str,
    ) -> IntegrationConnection | None:
        try:
            credentials = load_credentials(
                self._stripe_key(client_id)
            )
        except CredentialNotFoundError:
            return None

        return IntegrationConnection(
            client_id=client_id,
            provider=self.STRIPE_PROVIDER,
            credentials=dict(credentials),
        )

    def delete_stripe_connection(
        self,
        *,
        client_id: str,
    ) -> None:
        delete_credentials(self._stripe_key(client_id))
