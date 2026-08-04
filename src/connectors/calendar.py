# src/connectors/calendar.py

from datetime import datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def get_calendar_service(credentials: Credentials):
    """
    Build an authenticated Calendar service using credentials supplied
    by the OAuth layer.
    """
    return build(
        "calendar",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def get_upcoming_events(
    service,
    calendar_id: str = "primary",
    hours_ahead: int = 24,
) -> list[dict]:
    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(hours=hours_ahead)).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    return events_result.get("items", [])