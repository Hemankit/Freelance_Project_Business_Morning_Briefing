import os
import resend
from dotenv import load_dotenv

load_dotenv()

resend.api_key = os.getenv('RESEND_API_KEY')


def send_briefing_email(to_email, briefing_text, from_email="onboarding@resend.dev"):
    """
    Sends the AI-generated briefing as an email.
    from_email defaults to Resend's shared test address — swap once own domain is verified.
    """
    params = {
        "from": from_email,
        "to": [to_email],
        "subject": "Your Morning Briefing",
        "text": briefing_text,
    }

    response = resend.Emails.send(params)
    return response


if __name__ == '__main__':
    # quick manual test with fake briefing text
    test_briefing = "Good morning! You have one overdue payment ($200 from John) and a birthday reminder for March 3rd."
    result = send_briefing_email(
        to_email="hemankitv@gmail.com",  # replace with real signup email
        briefing_text=test_briefing
    )
    print(result)