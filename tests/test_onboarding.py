import uuid

from fastapi.testclient import TestClient

from src.api.routes.app import app
from src.api.routes.onboarding import _is_onboarding_complete
from src.repositories.client_repository import ClientRepository
from src.repositories.configuration_repository import RulesConfiguration
from src.repositories.integration_repository import IntegrationRepository


def _new_token() -> str:
    return f"test-client-{uuid.uuid4().hex[:8]}"


def _configuration(enabled_sources: list[str]) -> RulesConfiguration:
    return RulesConfiguration(
        client_id="ignored",
        recipient_email="owner@example.com",
        timezone="UTC",
        delivery_time="09:00",
        lookback_hours=24,
        rules_json={},
        enabled_sources=enabled_sources,
        updated_at="ignored",
    )


def test_is_onboarding_complete_no_configuration():
    assert not _is_onboarding_complete(
        None, google_connected=False, stripe_connected=False
    )


def test_is_onboarding_complete_missing_a_required_source():
    configuration = _configuration(["google_calendar", "stripe"])
    assert not _is_onboarding_complete(
        configuration, google_connected=True, stripe_connected=False
    )


def test_is_onboarding_complete_all_required_sources_connected():
    configuration = _configuration(["google_calendar", "stripe"])
    assert _is_onboarding_complete(
        configuration, google_connected=True, stripe_connected=True
    )


def test_first_visit_creates_pending_client_and_shows_form():
    token = _new_token()

    with TestClient(app) as client:
        response = client.get(f"/setup/{token}")

    assert response.status_code == 200
    assert "Recipient email" in response.text

    stored_client = ClientRepository().get_client(client_id=token)
    assert stored_client is not None
    assert stored_client.status == "pending_setup"


def test_save_configuration_for_unknown_client_returns_404():
    token = _new_token()

    with TestClient(app) as client:
        response = client.post(
            f"/setup/{token}/configuration",
            data={
                "recipient_email": "owner@example.com",
                "timezone": "UTC",
                "delivery_time": "09:00",
                "lookback_hours": "24",
                "enabled_sources": ["google_calendar"],
            },
        )

    assert response.status_code == 404


def test_save_configuration_rejects_invalid_email():
    token = _new_token()

    with TestClient(app) as client:
        client.get(f"/setup/{token}")  # provisions the client record

        response = client.post(
            f"/setup/{token}/configuration",
            data={
                "recipient_email": "not-an-email",
                "timezone": "UTC",
                "delivery_time": "09:00",
                "lookback_hours": "24",
                "enabled_sources": ["google_calendar"],
            },
        )

    assert response.status_code == 400


def test_full_onboarding_flow_activates_client():
    token = _new_token()

    with TestClient(app) as client:
        client.get(f"/setup/{token}")  # provisions the client record

        config_response = client.post(
            f"/setup/{token}/configuration",
            data={
                "recipient_email": "owner@example.com",
                "timezone": "UTC",
                "delivery_time": "09:00",
                "lookback_hours": "24",
                "enabled_sources": ["google_calendar"],
            },
            follow_redirects=False,
        )
        assert config_response.status_code == 303

        pending_page = client.get(f"/setup/{token}")
        assert "Connect Google Calendar" in pending_page.text

        # Simulate a successful OAuth callback without calling Google.
        IntegrationRepository().upsert_google_calendar_connection(
            client_id=token,
            credentials={"token": "fake"},
        )

        success_response = client.get(
            f"/setup/{token}", follow_redirects=True
        )

    assert success_response.status_code == 200
    assert "Connection Successful" in success_response.text

    stored_client = ClientRepository().get_client(client_id=token)
    assert stored_client.status == "active"
