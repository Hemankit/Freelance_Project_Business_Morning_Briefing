from src.connectors.calendar import get_calendar_service, get_upcoming_events
from src.connectors.stripe_connector import get_open_invoices
from src.transforms.calendar_to_event import calendar_to_event
from src.transforms.stripe_to_event import stripe_invoice_to_event
from src.rules.apply_rules import apply_rules
from src.summarize.generate_briefing import generate_briefing
from src.delivery.send_email import send_briefing_email

RECIPIENT_EMAIL = "hemankitv@gmail.com"  # your real signup email for now


def run():
    print("Fetching calendar events...")
    service = get_calendar_service()
    raw_calendar_events = get_upcoming_events(service)

    print("Fetching Stripe invoices...")
    raw_invoices = get_open_invoices()

    print("Transforming to standard schema...")
    calendar_events = [calendar_to_event(e) for e in raw_calendar_events]
    stripe_events = [stripe_invoice_to_event(inv.to_dict()) for inv in raw_invoices]

    print("Applying rules...")
    all_events = calendar_events + stripe_events
    final_events = apply_rules(all_events)

    print("Generating briefing...")
    briefing_text = generate_briefing(final_events)
    print("\n--- Briefing ---")
    print(briefing_text)

    print("\nSending email...")
    result = send_briefing_email(RECIPIENT_EMAIL, briefing_text)
    print(f"Sent! Email ID: {result['id']}")


if __name__ == '__main__':
    run()