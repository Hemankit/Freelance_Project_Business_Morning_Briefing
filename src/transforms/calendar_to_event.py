
from src.connectors.calendar import get_calendar_service, get_upcoming_events

def calendar_to_event(raw_event):
    """
    Converts a raw Google Calendar event into our standard event schema.
    Dead simple for now — no urgency logic yet, that comes once Stripe is in.
    """
    start = raw_event['start'].get('dateTime', raw_event['start'].get('date'))

    return {
        "category": "meeting",
        "customer": None,  # calendar events don't have a "customer" — leaving as None for now
        "title": raw_event.get('summary', '(no title)'),
        "time": start,
        "age_days": None,  # not relevant for calendar events
        "urgency": "info",  # placeholder — everything's just informational for now
        "source": "calendar"
    }

if __name__ == '__main__':
    service = get_calendar_service()
    events = get_upcoming_events(service)

    standardized = [calendar_to_event(e) for e in events]
    for event in standardized:
        print(event)