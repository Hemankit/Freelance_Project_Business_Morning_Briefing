Morning Briefing

A daily automated briefing that pulls data from a business's connected tools (currently Google Calendar and Stripe), summarizes what needs attention using AI, and delivers it as a single email each morning.

What it does

Every morning, the pipeline:

Fetches recent records from supported systems (Calendar, Stripe)
Converts them into a standardized event schema
Applies rules to filter/prioritize what matters
Asks Claude to summarize the selected events into plain English
Sends the briefing by email

No dashboard, no real-time monitoring, no prompting required — the goal is one calm, useful email, not another tool to check.

Status

MVP — working end to end. Currently supports a single client (manually configured), running on a daily schedule via GitHub Actions.

Architecture
src/
├── connectors/         # fetch raw data from each external API
│   ├── calendar.py
│   └── stripe_connector.py
│
├── transforms/          # convert raw API data into the standard event schema
│   ├── calendar_to_event.py
│   └── stripe_to_event.py
│
├── rules/                # decide what's shown / how it's prioritized
│   └── apply_rules.py
│
├── summarize/            # AI-generated plain-English briefing
│   └── generate_briefing.py
│
├── delivery/             # sends the final briefing
│   └── send_email.py
│
└── run.py                # orchestrator — the entry point that runs the full pipeline
The standard event schema

Every data source, regardless of origin, is transformed into the same shape before it reaches the rules or summary steps:

json
{
  "category": "overdue_payment",
  "customer": "ABC Plumbing",
  "amount": 1200,
  "age_days": 18,
  "urgency": "high",
  "source": "accounting_system"
}

This is what makes adding new integrations cheap — the rules and summarization logic never need to know or care where an event came from.

Setup
Prerequisites
Python 3.11+
A Google Cloud project with the Calendar API enabled (OAuth credentials)
A Stripe account (test mode is fine for development)
An Anthropic API key
A Resend account (for sending email)
Installation
bash
git clone <this-repo>
cd morning-briefing
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
Environment variables

Copy .env.example to .env and fill in your own values:

ANTHROPIC_API_KEY=
STRIPE_SECRET_KEY=
RESEND_API_KEY=
Google Calendar credentials
Create a Google Cloud project, enable the Calendar API
Create OAuth credentials (Desktop app type)
Download the credentials JSON and save it as credentials/credentials.json
Run python src/connectors/calendar.py once locally to complete the OAuth login — this generates credentials/token.json

Neither file should ever be committed to git (already covered in .gitignore).

Running locally
bash
python src/run.py

This runs the full pipeline once: fetch → transform → apply rules → summarize → send.

Deployment

Currently deployed via GitHub Actions, running on a daily schedule (.github/workflows/daily_briefing.yml). Credentials are stored as GitHub Secrets and written to disk at runtime, since GitHub Actions runners have no persistent filesystem between runs.

Manually trigger a run any time via the Actions tab → Run workflow, without waiting for the schedule.

Before pushing dependency changes

Test in a clean virtual environment first, to catch platform-specific issues (e.g. Windows-only packages) before they break CI:

bash
python -m venv test_env
test_env\Scripts\activate      # or source test_env/bin/activate on Mac/Linux
pip install -r requirements.txt
