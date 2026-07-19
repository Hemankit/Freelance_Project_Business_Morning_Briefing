from datetime import datetime, timezone
from src.connectors.stripe_connector import get_open_invoices

def stripe_invoice_to_event(invoice):
    """
    Converts a raw Stripe invoice (as a dict, from .to_dict()) into our standard event schema.
    """
    created = datetime.fromtimestamp(invoice['created'], tz=timezone.utc)
    age_days = (datetime.now(timezone.utc) - created).days

    return {
        "category": "overdue_payment",
        "customer": invoice.get('customer_email') or invoice.get('customer_name') or "Unknown customer",
        "amount": invoice['amount_due'] / 100,
        "age_days": age_days,
        "urgency": "high" if age_days >= 14 else "medium",  # simple placeholder rule, we'll refine later
        "source": "accounting_system"
    }

if __name__ == '__main__':
    invoices = get_open_invoices()
    if not invoices:
        print('No open invoices found.')
    else:
      for inv in invoices:
        inv = inv.to_dict()
        event = stripe_invoice_to_event(inv)
        print(event)