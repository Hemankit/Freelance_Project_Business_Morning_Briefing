# Morning Briefing

Morning Briefing is a multi-tenant service that connects a client's Google
Calendar and Stripe account, pulls in upcoming events and open invoices,
summarizes them with Claude (Anthropic) into a plain-English "morning
briefing," and emails it via Resend.

This README reflects the actual state of the codebase as of 2026-08-01 —
including what's finished, what's stubbed out, and what's known to be broken.

## Status at a glance

| Area | Status |
|---|---|
| Client onboarding (setup link, config form, OAuth connect) | Working end-to-end |
| Google Calendar OAuth + Stripe OAuth | Implemented |
| Encrypted credential storage | Implemented |
| Configuration storage (recipient, timezone, delivery time, sources) | Implemented |
| Calendar / Stripe connectors + transforms | Implemented (per-client credentials) |
| Rules engine | Stub — merges and sorts by urgency only, no real filtering |
| Briefing generation (Claude) + email delivery (Resend) | Implemented, but not yet wired to per-client data |
| Multi-tenant orchestration (`src/run.py`) | **Broken / stale** — predates OAuth, calls connectors with no arguments |
| `briefing_run_repository.py`, parts of `configuration_repository.py` history | Stub dataclasses, no persistence |
| Automated tests | None yet |

## How onboarding works today

1. An admin generates an opaque `setup_token` out of band and sends the
   client a link: `GET /setup/{setup_token}`.
2. On first visit, a bare client record is created (id + status only — the
   app intentionally stores no client PII such as name or contact email).
3. The client fills out a configuration form (recipient email, timezone,
   delivery time, lookback hours, which sources to enable) which is saved
   via `POST /setup/{setup_token}/configuration`.
4. The client connects whichever sources they enabled via
   `/auth/google` and `/auth/stripe` (+ callbacks). Each callback redirects
   back to `/setup/{setup_token}` so the page re-evaluates progress.
5. Once configuration is saved and every enabled source is connected, the
   client status flips from `pending_setup` to `active` and the client is
   redirected to `/setup_success`.

There's no admin-facing endpoint to mint `setup_token` links yet — an admin
mints/sends them manually.

## Project structure

```
src/
  api/routes/        FastAPI app + onboarding routes (setup, OAuth callbacks)
  auth/               Google & Stripe OAuth flows, credential serialize/refresh
  connectors/         Google Calendar and Stripe API wrappers (per-client creds)
  transforms/         Raw API responses -> standardized event dicts
  rules/              Event filtering/sorting (currently sort-only)
  summarize/          Claude-based briefing generation
  delivery/           Resend email sending
  repositories/       SQLite-backed data access (clients, config, integrations,
                      oauth state, briefing runs)
  storage/            Shared DB connection + encrypted credential store
  templates/          Jinja2 templates for the setup pages
  run.py              Single-tenant pipeline entry point — currently stale/broken
scripts/
  manage_client.py    Admin CLI: `show <client_id>` / `delete <client_id>`
data/                 SQLite database file lives here (data/app.db by default)
credentials/          Local OAuth client secrets / token cache (not committed)
```

## Data storage

- Single shared SQLite database at `data/app.db` (override with the
  `DATABASE_PATH` env var).
- Connection handling lives only in `src/storage/database.py`; each
  repository owns its own table schema and validation.
- OAuth/Stripe credentials are encrypted at rest via
  `src/storage/credentials_store.py` (Fernet) and accessed through
  `IntegrationRepository`.
- `ConfigurationRepository` and `ClientRepository` are fully implemented.
  `BriefingRunRepository` is still a stub with no persistence.

## Setup

### Prerequisites

- Python 3.11+
- A Google Cloud OAuth client (Calendar API scope)
- A Stripe Connect application (platform secret key + OAuth client)
- Anthropic API key (briefing generation)
- Resend API key (email delivery)

### Install

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> `requirements.txt` currently only lists `anthropic`, `google-api-python-client`,
> `google-auth`, `google-auth-oauthlib`, `python-dotenv`, `python-multipart`,
> `resend`, and `stripe`. It's missing `fastapi`, an ASGI server (e.g.
> `uvicorn`), and `cryptography`, all of which are imported by the code —
> install these manually until the file is updated.

### Environment variables

`.env.example` currently only documents `ANTHROPIC_API_KEY` and
`RESEND_API_KEY`. The onboarding flow additionally requires:

```
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI
STRIPE_CLIENT_ID
STRIPE_SECRET_KEY
STRIPE_REDIRECT_URI
CREDENTIALS_ENCRYPTION_KEY
DATABASE_PATH        (optional, defaults to data/app.db)
```

### Running the onboarding API

```powershell
uvicorn src.api.routes.app:app --reload
```

Then visit `/setup/{setup_token}` for any token you choose to mint.

### Admin CLI

```powershell
python scripts/manage_client.py show <client_id>
python scripts/manage_client.py delete <client_id> [--yes]
```

Read-only lookup and full deletion only — no edit command, since
configuration changes are expected to go through the client's own setup
link so app validation runs.

## Known gaps / next steps

- **`src/run.py` is not usable as-is.** It calls
  `get_calendar_service()` / `get_open_invoices()` with no arguments, but
  both now require per-client credentials. It predates the OAuth/multi-tenant
  storage layer and needs a rewrite, not incremental fixes.
- No per-client orchestration function exists yet that chains
  `ClientRepository` → `ConfigurationRepository` → `IntegrationRepository`
  (decrypted per-source credentials) → connectors → transforms →
  `apply_rules` → `generate_briefing` → `send_briefing_email` →
  `BriefingRunRepository`.
- Google credentials need a helper to rebuild a
  `google.oauth2.credentials.Credentials` object from the stored dict,
  including refresh-and-repersist handling (Stripe already has an
  equivalent in `stripe_oauth.get_stripe_account_id`).
- `apply_rules.py` is a placeholder — it only sorts by urgency, it doesn't
  filter or dedupe events yet.
- `BriefingRunRepository` has no persistence implemented.
- No automated tests exist for onboarding or the briefing pipeline.
- `requirements.txt` and `.env.example` need to be brought up to date (see
  above).
