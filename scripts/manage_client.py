"""
Admin CLI for looking up or removing one client's onboarding data.

Read-only lookup and full deletion only — there is no update command.
Configuration/credential changes should always go through the client's
setup link so the app's own validation runs.

Usage:
    python scripts/manage_client.py show <client_id>
    python scripts/manage_client.py delete <client_id> [--yes]
"""

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from src.repositories.client_repository import ClientRepository
from src.repositories.configuration_repository import ConfigurationRepository
from src.repositories.integration_repository import IntegrationRepository
from src.repositories.oauth_state_repository import OAuthStateRepository

_client_repository = ClientRepository()
_configuration_repository = ConfigurationRepository()
_integration_repository = IntegrationRepository()
_oauth_state_repository = OAuthStateRepository()


def show_client(client_id: str) -> None:
    client = _client_repository.get_client(client_id=client_id)

    if client is None:
        print(f"No client found for ID '{client_id}'.")
        return

    print(f"client_id:    {client.id}")
    print(f"status:       {client.status}")
    print(f"created_at:   {client.created_at}")
    print(f"updated_at:   {client.updated_at}")

    configuration = _configuration_repository.get_configuration(
        client_id=client_id
    )

    if configuration is None:
        print("configuration: not set")
    else:
        print("configuration:")
        print(f"  recipient_email:  {configuration.recipient_email}")
        print(f"  timezone:         {configuration.timezone}")
        print(f"  delivery_time:    {configuration.delivery_time}")
        print(f"  lookback_hours:   {configuration.lookback_hours}")
        print(f"  enabled_sources:  {configuration.enabled_sources}")
        print(f"  rules_json:       {configuration.rules_json}")
        print(f"  updated_at:       {configuration.updated_at}")

    google_connected = (
        _integration_repository.get_google_calendar_connection(
            client_id=client_id
        )
        is not None
    )
    stripe_connected = (
        _integration_repository.get_stripe_connection(
            client_id=client_id
        )
        is not None
    )

    print(f"google_calendar connected: {google_connected}")
    print(f"stripe connected:          {stripe_connected}")


def delete_client(client_id: str, *, skip_confirmation: bool) -> None:
    client = _client_repository.get_client(client_id=client_id)

    if client is None:
        print(f"No client found for ID '{client_id}'.")
        return

    if not skip_confirmation:
        answer = input(
            f"Delete all data for client '{client_id}' "
            f"({client.status})? This cannot be undone. [y/N] "
        )

        if answer.strip().lower() != "y":
            print("Aborted.")
            return

    deleted_states = _oauth_state_repository.delete_states_for_client(
        client_id=client_id
    )
    _integration_repository.delete_google_calendar_connection(
        client_id=client_id
    )
    _integration_repository.delete_stripe_connection(
        client_id=client_id
    )
    deleted_configuration = _configuration_repository.delete_configuration(
        client_id=client_id
    )
    _client_repository.delete_client(client_id=client_id)

    print(f"Deleted client '{client_id}'.")
    print(f"  pending oauth states removed: {deleted_states}")
    print(f"  configuration removed:        {deleted_configuration}")
    print("  google_calendar / stripe credentials removed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser(
        "show", help="Print a client's current configuration and connections."
    )
    show_parser.add_argument("client_id")

    delete_parser = subparsers.add_parser(
        "delete", help="Remove all stored data for a client."
    )
    delete_parser.add_argument("client_id")
    delete_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )

    args = parser.parse_args()

    if args.command == "show":
        show_client(args.client_id)
    elif args.command == "delete":
        delete_client(args.client_id, skip_confirmation=args.yes)


if __name__ == "__main__":
    sys.exit(main())
