"""Keep all functional tests isolated from any real application environment."""

import os
import secrets


# This affects only the pytest process and its children. No application/Neon
# database or persistent secret is used by the test suite.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
# Never inherit a real Redis URL from the developer's environment or .env.
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["ALLOW_PUBLIC_REGISTRATION"] = "true"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
# Override any local .env bootstrap values instead of reading real ones.
os.environ["FIRST_SUPERUSER_EMAIL"] = "unused@example.com"
os.environ["FIRST_SUPERUSER_PASSWORD"] = "unused-test-password-4827"
os.environ["FIRST_COMPANY_NAME"] = "Test Company"

# Legacy unit tests run without Redis; dedicated tests override the dependency
# with an isolated local Redis. This mutates only the pytest process.
from app.config import settings
settings.REDIS_URL = ""
