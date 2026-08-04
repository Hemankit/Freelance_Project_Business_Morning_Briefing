from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.auth import google_oauth, stripe_oauth
from src.repositories.client_repository import ClientRepository
from src.repositories.configuration_repository import (
    ConfigurationRepository,
    RulesConfiguration,
)
from src.repositories.integration_repository import IntegrationRepository
from src.repositories.oauth_state_repository import OAuthStateRepository

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

_client_repository = ClientRepository()
_configuration_repository = ConfigurationRepository()
_integration_repository = IntegrationRepository()
_oauth_state_repository = OAuthStateRepository()


def _is_onboarding_complete(
    configuration: RulesConfiguration | None,
    *,
    google_connected: bool,
    stripe_connected: bool,
) -> bool:
    """Whether every source the client selected has been connected."""
    if configuration is None:
        return False

    connected_sources = set()
    if google_connected:
        connected_sources.add("google_calendar")
    if stripe_connected:
        connected_sources.add("stripe")

    return set(configuration.enabled_sources) <= connected_sources


# ---------------------------------------------------------------------------
# Setup pages
# ---------------------------------------------------------------------------

# This endpoint serves the setup page for the Google OAuth flow. The setup_token is used to identify the user and ensure that the setup process is secure.
@router.get("/setup/{setup_token}")
def setup_page(request: Request, setup_token: str):
    client = _client_repository.get_client(client_id=setup_token)

    if client is None:
        # First visit: provision a bare client record behind this link.
        client = _client_repository.create_client(client_id=setup_token)

    configuration = _configuration_repository.get_configuration(
        client_id=setup_token
    )
    google_connected = (
        _integration_repository.get_google_calendar_connection(
            client_id=setup_token
        )
        is not None
    )
    stripe_connected = (
        _integration_repository.get_stripe_connection(client_id=setup_token)
        is not None
    )

    if _is_onboarding_complete(
        configuration,
        google_connected=google_connected,
        stripe_connected=stripe_connected,
    ):
        if client.status != "active":
            _client_repository.set_client_status(
                client_id=setup_token, status="active"
            )
        return RedirectResponse("/setup_success")

    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={
            "setup_token": setup_token,
            "configuration": configuration,
            "google_connected": google_connected,
            "stripe_connected": stripe_connected,
        },
    )


# POC defaults for fields not yet exposed on the setup form: a single global
# cron time is used for all clients (see BRIEFING_RUN_HOUR/MINUTE_UTC in app.py).
_DEFAULT_TIMEZONE = "UTC"
_DEFAULT_DELIVERY_TIME = "11:00"
_DEFAULT_LOOKBACK_HOURS = 24


@router.post("/setup/{setup_token}/configuration")
def save_configuration(
    setup_token: str,
    recipient_email: str = Form(...),
    enabled_sources: list[str] = Form([]),
):
    if _client_repository.get_client(client_id=setup_token) is None:
        raise HTTPException(status_code=404, detail="Unknown setup link.")

    try:
        _configuration_repository.save_configuration(
            client_id=setup_token,
            recipient_email=recipient_email,
            timezone=_DEFAULT_TIMEZONE,
            delivery_time=_DEFAULT_DELIVERY_TIME,
            lookback_hours=_DEFAULT_LOOKBACK_HOURS,
            rules_json={},
            enabled_sources=enabled_sources,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(f"/setup/{setup_token}", status_code=303)


# This endpoint serves the success page after the Google OAuth flow is completed. It indicates that the setup process was successful.
@router.get("/setup_success")
def setup_success_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="setup_success.html",
        context={},
    )


# ---------------------------------------------------------------------------
# Google Calendar OAuth
# ---------------------------------------------------------------------------

@router.get("/auth/google")
def start_google_auth(setup_token: str):
    """Redirect the client to Google's Calendar authorization page."""
    if _client_repository.get_client(client_id=setup_token) is None:
        raise HTTPException(status_code=404, detail="Unknown setup link.")

    authorization_url = google_oauth.create_authorization_url(
        client_id=setup_token,
        oauth_state_repository=_oauth_state_repository,
    )
    return RedirectResponse(authorization_url)


@router.get("/auth/google/callback")
def google_callback(request: Request, state: str):
    """Receive Google's redirect, exchange the code, and store credentials."""
    client_id = google_oauth.handle_oauth_callback(
        authorization_response=str(request.url),
        state=state,
        oauth_state_repository=_oauth_state_repository,
        integration_repository=_integration_repository,
    )
    return RedirectResponse(f"/setup/{client_id}")


# ---------------------------------------------------------------------------
# Stripe OAuth
# ---------------------------------------------------------------------------

@router.get("/auth/stripe")
def start_stripe_auth(setup_token: str):
    """Redirect the client to Stripe's Connect authorization page."""
    if _client_repository.get_client(client_id=setup_token) is None:
        raise HTTPException(status_code=404, detail="Unknown setup link.")

    authorization_url = stripe_oauth.create_authorization_url(
        client_id=setup_token,
        oauth_state_repository=_oauth_state_repository,
    )
    return RedirectResponse(authorization_url)


@router.get("/auth/stripe/callback")
def stripe_callback(code: str, state: str):
    """Receive Stripe's redirect, exchange the code, and store the account."""
    client_id = stripe_oauth.handle_oauth_callback(
        code=code,
        state=state,
        oauth_state_repository=_oauth_state_repository,
        integration_repository=_integration_repository,
    )
    return RedirectResponse(f"/setup/{client_id}")






