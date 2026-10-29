"""Keep all functional tests isolated from any real application environment."""

import os
import secrets
from urllib.parse import urlsplit

import pytest


# This affects only the pytest process and its children. No application/Neon
# database or persistent secret is used by the test suite.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
# Never inherit a real Redis URL from the developer's environment or .env.
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["ALLOW_PUBLIC_REGISTRATION"] = "true"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
# No real provider destinations or local Ollama exceptions from .env/the host.
os.environ["AI_ALLOWED_ORIGINS"] = ""
os.environ["AI_ALLOW_LOCAL_OLLAMA"] = "false"
# Override any local .env bootstrap values instead of reading real ones.
os.environ["FIRST_SUPERUSER_EMAIL"] = "unused@example.com"
os.environ["FIRST_SUPERUSER_PASSWORD"] = "unused-test-password-4827"
os.environ["FIRST_COMPANY_NAME"] = "Test Company"

# Legacy unit tests run without Redis; dedicated tests override the dependency
# with an isolated local Redis. This mutates only the pytest process.
from app.config import settings
from app.services.redis_store import create_redis_store

settings.REDIS_URL = ""


@pytest.fixture
def redis_store():
    """Only the explicitly selected local Redis; never a hosted service."""
    url = os.environ.get("CI_TEST_REDIS_URL", "")
    if not url:
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("CI_TEST_REDIS_URL must point to the disposable local Redis service")
        pytest.skip("Set CI_TEST_REDIS_URL to an isolated local Redis to run integration tests")
    try:
        parsed = urlsplit(url)
        safe = (
            parsed.scheme == "redis"
            and parsed.hostname == "127.0.0.1"
            and parsed.port is not None and parsed.port >= 1024
            and parsed.username is None and parsed.password is None
            and parsed.path in {"", "/0"}
            and not parsed.query and not parsed.fragment
        )
    except ValueError:
        safe = False
    if not safe:
        pytest.fail("CI_TEST_REDIS_URL must be an unauthenticated loopback-only Redis URL")

    prefix = f"primecrm-test-{secrets.token_hex(12)}"
    store = create_redis_store(url, "test-only-signing-key-with-more-than-32-characters", prefix)
    store.check_writable()
    try:
        yield store
    finally:
        # Delete only keys under this run's random namespace; never FLUSHDB.
        for key in store.client.scan_iter(match=f"{prefix}:*", count=100):
            store.client.delete(key)
        store.close()
