"""Test env setup.

Must run before any `src.*` module is imported: several modules
(google_oauth.py, stripe_oauth.py, storage/database.py) read required
env vars / build constants at import time, not lazily.
"""

import os
import tempfile

from cryptography.fernet import Fernet

_test_db_dir = tempfile.mkdtemp(prefix="morning_briefing_test_")

os.environ.setdefault(
    "DATABASE_PATH", os.path.join(_test_db_dir, "test_app.db")
)
os.environ.setdefault(
    "CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode()
)
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
os.environ.setdefault(
    "GOOGLE_REDIRECT_URI", "http://testserver/auth/google/callback"
)
os.environ.setdefault("STRIPE_CLIENT_ID", "test-stripe-client-id")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault(
    "STRIPE_REDIRECT_URI", "http://testserver/auth/stripe/callback"
)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("RESEND_API_KEY", "test-resend-key")
