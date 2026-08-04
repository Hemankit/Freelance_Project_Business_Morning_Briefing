# src/auth/stripe_oauth.py

import os
from typing import Any
from urllib.parse import urlencode

import stripe
from fastapi import HTTPException

from src.repositories.oauth_state_repository import OAuthStateInvalidError


STRIPE_CLIENT_ID = os.environ["STRIPE_CLIENT_ID"].strip()
STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"].strip()
STRIPE_REDIRECT_URI = os.environ["STRIPE_REDIRECT_URI"].strip()

STRIPE_AUTHORIZE_URL = "https://connect.stripe.com/oauth/authorize"


def get_stripe_client() -> stripe.StripeClient:
    """
    Create a Stripe client using the platform's secret key.

    This key belongs to the Morning Briefing Stripe platform,
    not to an individual customer.
    """
    return stripe.StripeClient(STRIPE_SECRET_KEY)


def create_authorization_url(
    *,
    client_id: str,
    oauth_state_repository,
) -> str:
    """
    Create the URL where the client connects their Stripe account.

    oauth_state_repository persists a hashed, provider-bound state token
    keyed by client_id.
    """
    created_state = oauth_state_repository.create_state(
        client_id=client_id,
        provider="stripe",
        setup_session_id=client_id,
    )

    params = {
        "response_type": "code",
        "client_id": STRIPE_CLIENT_ID,
        "scope": "read_write",
        "state": created_state.raw_state,
        "redirect_uri": STRIPE_REDIRECT_URI,
    }

    return f"{STRIPE_AUTHORIZE_URL}?{urlencode(params)}"


def handle_oauth_callback(
    *,
    code: str,
    state: str,
    oauth_state_repository,
    integration_repository,
) -> str:
    """
    Validate the callback, exchange the authorization code for a connected
    account ID, and save credentials for the correct client.

    Returns the connected client_id.
    """
    try:
        state_record = oauth_state_repository.consume_state(
            raw_state=state,
            provider="stripe",
        )
    except OAuthStateInvalidError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state.",
        ) from exc

    client_id = state_record.client_id

    stripe_client = get_stripe_client()

    try:
        token_response = stripe_client.oauth.token(
            params={
                "grant_type": "authorization_code",
                "code": code,
            }
        )
    except stripe.InvalidGrantError as exc:
        raise HTTPException(
            status_code=400,
            detail="Stripe OAuth code is invalid or already used.",
        ) from exc

    stripe_account_id = token_response.stripe_user_id

    if not stripe_account_id or not stripe_account_id.startswith("acct_"):
        raise HTTPException(
            status_code=400,
            detail="Stripe did not return a valid connected account ID.",
        )

    integration_repository.upsert_stripe_connection(
        client_id=client_id,
        credentials=serialize_token_response(token_response),
    )

    return client_id


def serialize_token_response(token_response: Any) -> dict[str, Any]:
    """
    Convert Stripe's OAuth token response into a database-friendly dictionary.

    This dictionary must be encrypted before being persisted.
    """
    return {
        "stripe_user_id": token_response.stripe_user_id,
        "access_token": token_response.access_token,
        "refresh_token": token_response.refresh_token,
        "token_type": token_response.token_type,
        "scope": token_response.scope,
        "livemode": token_response.livemode,
        "stripe_publishable_key": token_response.stripe_publishable_key,
    }


def get_stripe_account_id(
    *,
    client_id: str,
    integration_repository,
) -> str:
    """
    Load the Stripe connected account ID for a client.

    The account ID can be passed directly to the stripe_connector functions
    as the stripe_account_id argument.
    """
    connection = integration_repository.get_stripe_connection(
        client_id=client_id
    )

    if connection is None:
        raise HTTPException(
            status_code=404,
            detail="Stripe is not connected for this client.",
        )

    stripe_account_id = connection.credentials.get("stripe_user_id")

    if not stripe_account_id or not stripe_account_id.startswith("acct_"):
        raise HTTPException(
            status_code=400,
            detail="Stripe connection data is invalid. Please reconnect.",
        )

    return stripe_account_id
