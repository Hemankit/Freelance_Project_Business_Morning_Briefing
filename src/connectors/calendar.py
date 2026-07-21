import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
CREDENTIALS_PATH = 'credentials/credentials.json'  # the JSON downloaded
TOKEN_PATH = 'credentials/token.json'  # this gets auto-created after first login

import json

def ensure_credential_files():
    """On GitHub Actions, credentials/token don't exist as files yet — 
    write them from environment variables if they're missing."""
    os.makedirs('credentials', exist_ok=True)

    if not os.path.exists(CREDENTIALS_PATH) and os.getenv('GOOGLE_CREDENTIALS_JSON'):
        with open(CREDENTIALS_PATH, 'w') as f:
            f.write(os.getenv('GOOGLE_CREDENTIALS_JSON'))

    if not os.path.exists(TOKEN_PATH) and os.getenv('GOOGLE_TOKEN_JSON'):
        with open(TOKEN_PATH, 'w') as f:
            f.write(os.getenv('GOOGLE_TOKEN_JSON'))


def get_calendar_service():
    ensure_credential_files()
    creds = None

    # token.json stores your login after the first successful auth,
    # so you don't have to log in every single time
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # if there's no valid token, go through the login flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        # save the token for next time
        with open(TOKEN_PATH, 'w') as token_file:
            token_file.write(creds.to_json())

    service = build('calendar', 'v3', credentials=creds)
    return service

def get_upcoming_events(service, calendar_id='primary', hours_ahead=24):
    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(hours=hours_ahead)).isoformat()

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])
    return events

if __name__ == '__main__':
    # quick manual test: just confirm we can connect and list calendars
    service = get_calendar_service()
    events = get_upcoming_events(service)
    if not events:
        print('No upcoming events found.')
    else:
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            print(start, event['summary'])