# src/auth/google_oauth.py

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from src.repositories.oauth_state_repository import OAuthStateInvalidError


SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
]

GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"].strip()
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"].strip()
GOOGLE_REDIRECT_URI = os.environ["GOOGLE_REDIRECT_URI"].strip()


def get_google_client_config() -> dict[str, Any]:
    """
    Build the Google OAuth client configuration from environment variables.

    These credentials identify your application, not an individual client.
    """
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }


def create_google_flow(
    *,
    state: str | None = None,
) -> Flow:
    """
    Create a web-server OAuth flow.

    The same configured redirect URI must be registered in Google Cloud.
    """
    flow = Flow.from_client_config(
        client_config=get_google_client_config(),
        scopes=SCOPES,
        state=state,
    )

    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


def create_authorization_url(
    *,
    client_id: str,
    oauth_state_repository,
) -> str:
    """
    Create the URL where the client grants Calendar access.

    oauth_state_repository persists a hashed, provider-bound state token
    keyed by client_id.
    """
    created_state = oauth_state_repository.create_state(
        client_id=client_id,
        provider="google_calendar",
        setup_session_id=client_id,
    )

    flow = create_google_flow(state=created_state.raw_state)

    authorization_url, returned_state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    # Normally returned_state should be the same state supplied to the flow.
    if returned_state != created_state.raw_state:
        raise RuntimeError("Google OAuth state generation mismatch.")

    return authorization_url


def handle_oauth_callback(
    *,
    authorization_response: str,
    state: str,
    oauth_state_repository,
    integration_repository,
) -> str:
    """
    Validate the callback, exchange the authorization code for tokens,
    and save credentials for the correct client.

    Returns the connected client_id.
    """
    try:
        state_record = oauth_state_repository.consume_state(
            raw_state=state,
            provider="google_calendar",
        )
    except OAuthStateInvalidError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state.",
        ) from exc

    client_id = state_record.client_id

    flow = create_google_flow(state=state)

    flow.fetch_token(
        authorization_response=authorization_response,
    )

    credentials = flow.credentials

    if not credentials.refresh_token:
        raise HTTPException(
            status_code=400,
            detail=(
                "Google did not return a refresh token. "
                "The client may need to revoke the application's access "
                "and reconnect."
            ),
        )

    integration_repository.upsert_google_calendar_connection(
        client_id=client_id,
        credentials=serialize_credentials(credentials),
    )

    return client_id


def serialize_credentials(credentials: Credentials) -> dict[str, Any]:
    """
    Convert Google's Credentials object into a database-friendly dictionary.

    This dictionary must be encrypted before being persisted.
    """
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes or SCOPES),
        "expiry": (
            credentials.expiry.isoformat()
            if credentials.expiry
            else None
        )
    }


def deserialize_credentials(
    stored_credentials: dict[str, Any],
) -> Credentials:
    """
    Reconstruct Google's Credentials object from stored integration data.
    """
    expiry_value = stored_credentials.get("expiry")
    expiry = None

    if expiry_value:
        expiry = datetime.fromisoformat(
            expiry_value.replace("Z", "+00:00")
        )

        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

    return Credentials(
        token=stored_credentials.get("token"),
        refresh_token=stored_credentials.get("refresh_token"),
        token_uri=stored_credentials["token_uri"],
        client_id=stored_credentials["client_id"],
        client_secret=stored_credentials["client_secret"],
        scopes=stored_credentials.get("scopes", SCOPES),
        expiry=expiry,
    )


def get_valid_credentials(
    *,
    client_id: str,
    integration_repository,
) -> Credentials:
    """
    Load one client's credentials and refresh them when necessary.
    """
    connection = (
        integration_repository.get_google_calendar_connection(
            client_id=client_id
        )
    )

    if connection is None:
        raise HTTPException(
            status_code=404,
            detail="Google Calendar is not connected for this client.",
        )

    # Assumes the repository decrypts the credentials before returning them.
    credentials = deserialize_credentials(connection.credentials)

    if credentials.valid:
        return credentials

    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception as exc:
            raise RuntimeError(
                "Google Calendar authorization could not be refreshed."
            ) from exc

        integration_repository.upsert_google_calendar_connection(
            client_id=client_id,
            credentials=serialize_credentials(credentials),
        )

        return credentials

    # If the credentials are invalid and cannot be refreshed, the client
    # must reconnect to Google Calendar.

    raise RuntimeError(
        "Google Calendar must be reconnected for this client."
    )