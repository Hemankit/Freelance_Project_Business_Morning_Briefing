import os
import json
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))


def generate_briefing(events):
    """
    Takes the final, rules-filtered list of standardized events
    and asks Claude to write a concise morning briefing.
    """
    if not events:
        return "No items need your attention today."

    events_json = json.dumps(events, indent=2)

    prompt = f"""You are writing a concise morning briefing for a small business owner.

Below is a list of events from their calendar and accounting system, already sorted by urgency (high, medium, info).

Write a short, plain-English summary. Rules:
- No Markdown formatting whatsoever — no asterisks, no hashes, no backticks, no bold, no italics
- Plain text only; use line breaks and dashes for structure
- Group by urgency, high first
- Use plain sentences, not a data dump — write like a helpful assistant, not a report
- If nothing urgent, say so plainly and briefly mention the rest

Events:
{events_json}
"""

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


if __name__ == '__main__':
    # quick manual test with fake data
    test_events = [
        {"category": "overdue_payment", "customer": "deion@gmail.com", "amount": 200.0, "age_days": 0, "urgency": "medium", "source": "accounting_system"},
        {"category": "meeting", "customer": None, "title": "Happy birthday!", "time": "2027-03-03", "age_days": None, "urgency": "info", "source": "calendar"}
    ]
    print(generate_briefing(test_events))