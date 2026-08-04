# src/connectors/stripe_connector.py

import os
from typing import Any

import stripe


def get_stripe_client() -> stripe.StripeClient:
    """
    Create a Stripe client using the platform's secret key.

    This key belongs to the Morning Briefing Stripe platform,
    not to an individual customer.
    """
    secret_key = os.getenv("STRIPE_SECRET_KEY")

    if not secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured.")

    return stripe.StripeClient(secret_key)


def get_recent_charges(
    *,
    stripe_account_id: str,
    limit: int = 10,
) -> list[Any]:
    """
    Retrieve recent charges belonging to one connected Stripe account.
    """
    if not stripe_account_id.startswith("acct_"):
        raise ValueError("Invalid Stripe connected account ID.")

    client = get_stripe_client()

    response = client.charges.list(
        params={
            "limit": limit,
        },
        options={
            "stripe_account": stripe_account_id,
        },
    )

    return response.data


def get_open_invoices(
    *,
    stripe_account_id: str,
    limit: int = 10,
) -> list[Any]:
    """
    Retrieve open invoices belonging to one connected Stripe account.
    """
    if not stripe_account_id.startswith("acct_"):
        raise ValueError("Invalid Stripe connected account ID.")

    client = get_stripe_client()

    response = client.invoices.list(
        params={
            "status": "open",
            "limit": limit,
        },
        options={
            "stripe_account": stripe_account_id,
        },
    )

    return response.data