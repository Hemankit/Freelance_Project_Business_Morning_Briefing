import os
import stripe
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')


def get_recent_charges(limit=10):
    charges = stripe.Charge.list(limit=limit)
    return charges['data']


def get_open_invoices(limit=10):
    invoices = stripe.Invoice.list(status='open', limit=limit)
    return invoices['data']


if __name__ == '__main__':
    print("--- Recent charges ---")
    charges = get_recent_charges()
    for c in charges:
        c = c.to_dict()
        print(f"{c['id']} — amount: {c['amount']/100} {c['currency']} — status: {c['status']}")

    print("\n--- Open invoices ---")
    invoices = get_open_invoices()
    for inv in invoices:
        inv = inv.to_dict()
        print(f"{inv['id']} — customer: {inv.get('customer_email')} — amount due: {inv['amount_due']/100}")