"""
Multi-tenant morning briefing pipeline.

Usage:
    python -m src.run <client_id>   # run one client
    python -m src.run               # run every active client
"""

import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

from src.auth import google_oauth, stripe_oauth
from src.connectors.calendar import get_calendar_service, get_upcoming_events
from src.connectors.stripe_connector import get_open_invoices
from src.delivery.send_email import send_briefing_email
from src.repositories.briefing_run_repository import (
    BriefingRun,
    BriefingRunRepository,
)
from src.repositories.client_repository import ClientRepository
from src.repositories.configuration_repository import ConfigurationRepository
from src.repositories.integration_repository import IntegrationRepository
from src.rules.apply_rules import apply_rules
from src.summarize.generate_briefing import generate_briefing
from src.transforms.calendar_to_event import calendar_to_event
from src.transforms.stripe_to_event import stripe_invoice_to_event

_client_repository = ClientRepository()
_configuration_repository = ConfigurationRepository()
_integration_repository = IntegrationRepository()
_briefing_run_repository = BriefingRunRepository()


def _fetch_calendar_events(
    client_id: str,
    lookback_hours: int,
) -> list[dict]:
    credentials = google_oauth.get_valid_credentials(
        client_id=client_id,
        integration_repository=_integration_repository,
    )
    service = get_calendar_service(credentials)
    raw_events = get_upcoming_events(service, hours_ahead=lookback_hours)
    return [calendar_to_event(event) for event in raw_events]


def _fetch_stripe_events(client_id: str) -> list[dict]:
    stripe_account_id = stripe_oauth.get_stripe_account_id(
        client_id=client_id,
        integration_repository=_integration_repository,
    )
    raw_invoices = get_open_invoices(stripe_account_id=stripe_account_id)
    return [
        stripe_invoice_to_event(invoice.to_dict())
        for invoice in raw_invoices
    ]


def run_for_client(client_id: str) -> BriefingRun:
    """Fetch, summarize, and deliver one morning briefing for one client."""
    client = _client_repository.get_client(client_id=client_id)

    if client is None:
        raise ValueError(f"No client found for ID '{client_id}'.")

    configuration = _configuration_repository.get_configuration(
        client_id=client_id
    )

    if configuration is None:
        raise ValueError(
            f"Client '{client_id}' has no rules configuration set up."
        )

    run = _briefing_run_repository.start_run(client_id=client_id)

    def fail(stage: str, exc: Exception, **counts: int) -> BriefingRun:
        return _briefing_run_repository.fail_run(
            run_id=run.id,
            error_stage=stage,
            error_message=str(exc),
            **counts,
        )

    calendar_events: list[dict] = []
    if "google_calendar" in configuration.enabled_sources:
        try:
            calendar_events = _fetch_calendar_events(
                client_id, configuration.lookback_hours
            )
        except Exception as exc:
            return fail("calendar_fetch", exc)

    stripe_events: list[dict] = []
    if "stripe" in configuration.enabled_sources:
        try:
            stripe_events = _fetch_stripe_events(client_id)
        except Exception as exc:
            return fail(
                "stripe_fetch",
                exc,
                calendar_event_count=len(calendar_events),
            )

    calendar_event_count = len(calendar_events)
    stripe_event_count = len(stripe_events)

    try:
        final_events = apply_rules(
            calendar_events + stripe_events, client_id=client_id
        )
    except Exception as exc:
        return fail(
            "apply_rules",
            exc,
            calendar_event_count=calendar_event_count,
            stripe_event_count=stripe_event_count,
        )

    selected_event_count = len(final_events)

    try:
        briefing_text = generate_briefing(final_events)
    except Exception as exc:
        return fail(
            "generate_briefing",
            exc,
            calendar_event_count=calendar_event_count,
            stripe_event_count=stripe_event_count,
            selected_event_count=selected_event_count,
        )

    try:
        email_result = send_briefing_email(
            configuration.recipient_email,
            briefing_text,
        )
    except Exception as exc:
        return fail(
            "send_email",
            exc,
            calendar_event_count=calendar_event_count,
            stripe_event_count=stripe_event_count,
            selected_event_count=selected_event_count,
        )

    email_message_id = getattr(email_result, "id", None)
    if email_message_id is None and isinstance(email_result, dict):
        email_message_id = email_result.get("id")

    return _briefing_run_repository.complete_run(
        run_id=run.id,
        calendar_event_count=calendar_event_count,
        stripe_event_count=stripe_event_count,
        selected_event_count=selected_event_count,
        email_message_id=email_message_id,
    )


def run_all_active_clients() -> list[BriefingRun]:
    """Run the briefing pipeline for every active client.

    One client raising (e.g. its record vanished mid-run) must not stop the
    rest of the batch from getting their briefing.
    """
    results = []
    for client in _client_repository.list_clients(status="active"):
        try:
            results.append(run_for_client(client.id))
        except Exception:
            logger.exception(
                "briefing run crashed for client %s", client.id
            )
    return results


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(run_for_client(sys.argv[1]))
    else:
        for briefing_run in run_all_active_clients():
            print(briefing_run)