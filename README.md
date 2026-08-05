# Morning Briefing

Morning Briefing sends a AI-generated daily email for a small business. It collects actionable information from the business's connected tools, currently Google Calendar and Stripe, then filters, prioritizes, summarizes, and delivers it without requiring a dashboard or daily prompting.

## Project Evolution

Morning Briefing began as a deliberately narrow proof of the core product loop: one manually configured client, two data sources, one scheduled run, and one useful email. That first version validated the important question early: could Calendar and Stripe activity be normalized and turned into a concise briefing worth receiving each morning?

Once that workflow worked end to end, the project evolved from a single-client script into a deployable multi-client service.

| Stage | What changed | Why it mattered |
| --- | --- | --- |
| Core pipeline | Added connectors for Google Calendar and Stripe, normalized their output, applied rules, generated a Claude summary, and delivered it through Resend. | Established a source-agnostic pipeline so new integrations do not require rewriting the rules or summarization layers. |
| Client isolation | Replaced manual configuration with client records, per-client source settings, recipient emails, and briefing-run history. | Made the system capable of serving more than one business while retaining an auditable record of each delivery. |
| Self-service onboarding | Added FastAPI setup pages and Google/Stripe OAuth callbacks. | Removed the need to manually collect or paste each client's credentials into the application. |
| Secure persistence | Added shared SQLite persistence, encrypted OAuth credentials, expiring OAuth state, and a Railway volume. | Protected sensitive connection data and ensured configuration survives restarts and deployments. |
| Reliable operations | Added active/paused client states, isolated per-client failures, run-stage error records, an admin CLI, and an in-process daily scheduler. | One broken integration no longer prevents other clients from receiving their briefings, and operational support has clear inspection and cleanup tools. |

## Current State

The MVP now supports multiple clients. Each client is provisioned from a unique setup URL, selects Google Calendar and/or Stripe, completes the relevant OAuth flow, and receives a daily email at its configured recipient address.

The production web service runs on Railway. It uses a persistent SQLite database for client configuration, briefing-run history, OAuth state, and encrypted integration credentials. APScheduler runs the briefing pipeline for every active client on a shared daily UTC schedule.

## How It Works

1. Visit `/setup/{setup_token}` to create or resume a client's onboarding.
2. Enter a recipient email and choose Google Calendar, Stripe, or both.
3. Connect each selected source through its OAuth flow.
4. Once every selected source is connected, the client becomes active.
5. At the scheduled time, the service fetches source data, converts it into normalized events, applies rules, asks Claude for a concise plain-text summary, and sends the result with Resend.

If one client's run fails, the scheduler logs the failure and continues processing the remaining active clients. Each run records its source counts, selected-event count, email message ID, and any failed stage.

## Architecture

```text
src/
  api/routes/          FastAPI setup pages and OAuth callbacks
  auth/                Google and Stripe OAuth flows
  connectors/          External API reads
  transforms/          Source records to normalized events
  rules/               Event filtering and prioritization
  summarize/           Claude briefing generation
  delivery/            Resend email delivery
  repositories/        Client, configuration, run, and OAuth-state persistence
  storage/             Shared SQLite and encrypted credential storage
  run.py               Single-client and all-active-clients pipeline entry points
scripts/manage_client.py  Admin CLI for inspecting or deleting client data
```

## Normalized Events

Connectors are transformed before the rules and summarization stages, so downstream code works with a consistent event shape. Calendar events produce informational meeting events; Stripe open invoices produce payment events with urgency based on age.

```json
{
  "category": "overdue_payment",
  "customer": "ABC Plumbing",
  "amount": 1200.0,
  "age_days": 18,
  "urgency": "high",
  "source": "accounting_system"
}
```

## Local Development

### Prerequisites

- Python 3.11 or later
- Google Cloud OAuth web-application credentials with the Calendar API enabled
- A Stripe Connect platform application
- Anthropic API access
- A Resend API key

### Install

```bash
git clone <repository-url>
cd Morning_Briefing
python -m venv venv

# Windows PowerShell
.\venv\Scripts\Activate.ps1

# macOS/Linux
source venv/bin/activate

pip install -r requirements-dev.txt
```

### Configure Environment

Create a `.env` file in the repository root. Do not commit it.

```dotenv
# Application services
ANTHROPIC_API_KEY=
RESEND_API_KEY=

# Google Calendar OAuth web application
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# Stripe Connect platform
STRIPE_CLIENT_ID=
STRIPE_SECRET_KEY=
STRIPE_REDIRECT_URI=http://localhost:8000/auth/stripe/callback

# Generate once with: Fernet.generate_key().decode()
CREDENTIALS_ENCRYPTION_KEY=

# Optional local defaults
DATABASE_PATH=data/app.db
BRIEFING_RUN_HOUR_UTC=11
BRIEFING_RUN_MINUTE_UTC=0
```

Register the exact Google and Stripe redirect URIs above with their respective providers. For a deployed environment, the redirect URIs must use that environment's public HTTPS URL, for example `https://<your-domain>/auth/google/callback` and `https://<your-domain>/auth/stripe/callback`.

`CREDENTIALS_ENCRYPTION_KEY` encrypts OAuth credentials before they are stored in SQLite. Generate it once and retain the same value; changing it prevents the app from decrypting existing connections.

### Start the Web App

```bash
uvicorn src.api.routes.app:app --reload
```

Open `http://localhost:8000/setup/<unique-setup-token>` to provision and configure a client. The setup token is the client ID, so use a new unpredictable value for each client.

The onboarding form currently stores a 24-hour lookback and defaults to UTC/11:00. The scheduler time is global for all active clients and is controlled by `BRIEFING_RUN_HOUR_UTC` and `BRIEFING_RUN_MINUTE_UTC`.

## Running Briefings Manually

Run one client:

```bash
python -m src.run <client_id>
```

Run every active client:

```bash
python -m src.run
```

Inspect or remove an onboarded client:

```bash
python scripts/manage_client.py show <client_id>
python scripts/manage_client.py delete <client_id>
python scripts/manage_client.py delete <client_id> --yes
```

## Deployment

The `Procfile` starts the FastAPI service with Uvicorn. The service's process also owns the daily APScheduler job, so deployment needs one running web process.

For Railway:

1. Set the production environment variables listed above, including public HTTPS OAuth callback URLs.
2. Attach a volume at `/app/data`.
3. Set `DATABASE_PATH=/app/data/app.db` so the SQLite database and encrypted credentials persist across deploys and restarts.
4. Set the desired global schedule with `BRIEFING_RUN_HOUR_UTC` and `BRIEFING_RUN_MINUTE_UTC`.

## Tests

Run the test suite from the repository root:

```bash
python -m pytest -v
```

The tests use a temporary SQLite database and mock OAuth persistence rather than contacting Google or Stripe.
