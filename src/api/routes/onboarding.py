from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.auth import google_oauth, stripe_oauth
from src.repositories.client_repository import ClientRepository
from src.repositories.integration_repository import IntegrationRepository
from src.repositories.oauth_state_repository import OAuthStateRepository

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

_client_repository = ClientRepository()
_integration_repository = IntegrationRepository()
_oauth_state_repository = OAuthStateRepository()


# ---------------------------------------------------------------------------
# Setup pages
# ---------------------------------------------------------------------------

# This endpoint serves the setup page for the Google OAuth flow. The setup_token is used to identify the user and ensure that the setup process is secure.
@router.get("/setup/{setup_token}")
def setup_page(
    request: Request,
    setup_token: str,
    business_name: str | None = None,
    contact_email: str | None = None,
):
    client = _client_repository.get_client(client_id=setup_token)

    if client is None:
        # First visit: provision the client record behind this link.
        if not business_name or not contact_email:
            raise HTTPException(
                status_code=404,
                detail="Unknown or expired setup link.",
            )

        client = _client_repository.create_client(
            client_id=setup_token,
            business_name=business_name,
            contact_email=contact_email,
        )

    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={"setup_token": setup_token},
    )


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
    google_oauth.handle_oauth_callback(
        authorization_response=str(request.url),
        state=state,
        oauth_state_repository=_oauth_state_repository,
        integration_repository=_integration_repository,
    )
    return RedirectResponse("/setup_success")


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
    stripe_oauth.handle_oauth_callback(
        code=code,
        state=state,
        oauth_state_repository=_oauth_state_repository,
        integration_repository=_integration_repository,
    )
    return RedirectResponse("/setup_success")






