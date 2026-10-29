"""Optional AI credential integration on an explicitly disposable local PostgreSQL.

CI points this at its own PostgreSQL service after migrations. Tests never use
DATABASE_URL for this purpose and reject non-loopback or unexpected databases.
All rows are rolled back at the end, including API commits (nested savepoints).
PostgreSQL sequences may still advance, so the database must be disposable.
"""

import os
import re
import secrets

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.core.security import create_access_token
from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.user import User
from app.services.ai_service.credentials import CREDENTIAL_PREFIX, decrypt_credential


def disposable_postgres_url():
    value = os.environ.get("CI_TEST_POSTGRES_URL", "")
    if not value:
        pytest.skip("CI_TEST_POSTGRES_URL is not set; no PostgreSQL integration database selected")
    try:
        url = make_url(value)
        safe_name = url.database == "primecrm_ci" or bool(re.fullmatch(r"primecrm_ai_ci_[0-9a-f]{16}", url.database or ""))
        safe = (
            url.drivername in {"postgresql", "postgresql+psycopg2"}
            and url.host == "127.0.0.1"
            and url.port is not None and 1024 <= url.port <= 65535
            and safe_name and not url.query
        )
    except Exception:
        safe = False
    if not safe:
        pytest.fail("CI_TEST_POSTGRES_URL must refer to the disposable, explicitly named local PostgreSQL test database")
    return value


def test_ai_credentials_with_real_postgres_and_isolated_mock_provider(monkeypatch):
    url = disposable_postgres_url()
    monkeypatch.setattr(settings, "SECRET_KEY", "fictitious-postgres-test-key-only-46289-enough-characters")
    monkeypatch.setattr(settings, "APP_ENV", "test")
    fake_key = "sk-fictitious-postgres-ai-test-key-12345"
    engine = create_engine(url)
    connection = engine.connect()
    outer = connection.begin()
    factory = sessionmaker(bind=connection, autoflush=False, join_transaction_mode="create_savepoint")
    previous_overrides = dict(app.dependency_overrides)
    unique = secrets.token_hex(12)
    slug = f"ai-rollback-test-{unique}"
    observed = []
    client = None
    try:
        with factory() as db:
            company = Company(name="Disposable AI Test", slug=slug)
            db.add(company)
            db.flush()
            user = User(email=f"ai-{unique}@example.test", first_name="Test", last_name="Admin", hashed_password="unused", role="admin", company_id=company.id)
            db.add(user)
            db.flush()
            company_id, user_id, session_nonce = company.id, user.id, user.session_nonce
            db.commit()

        def override_db():
            with factory() as db:
                yield db

        async_client = httpx.AsyncClient
        def mocked_client(*args, **kwargs):
            def handler(request):
                observed.append(request)
                return httpx.Response(200, json={"data": [{"id": "fake-model"}]})
            kwargs["transport"] = httpx.MockTransport(handler)
            kwargs["trust_env"] = False
            return async_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", mocked_client)
        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {create_access_token(user_id, session_nonce=session_nonce)}"}
        created = client.post("/api/v1/ai/providers", headers=headers, json={
            "provider": "openai_compat", "name": "Disposable provider", "is_active": True,
            "api_base_url": "https://fake-provider.example.invalid/v1", "api_key": fake_key,
        })
        assert created.status_code == 200
        provider_id = created.json()["id"]
        stored = connection.execute(text("SELECT api_key_encrypted FROM ai_provider_configs WHERE id = :id"), {"id": provider_id}).scalar_one()
        assert stored.startswith(CREDENTIAL_PREFIX) and fake_key not in stored
        assert decrypt_credential(stored, company_id, provider_id) == fake_key
        tested = client.post("/api/v1/ai/providers/test", headers=headers, json={"provider_id": provider_id})
        assert tested.status_code == 200 and tested.json()["models"] == ["fake-model"]
        assert fake_key not in created.text + tested.text
        assert len(observed) == 1 and observed[0].headers["authorization"] == f"Bearer {fake_key}"
    finally:
        if client:
            client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        outer.rollback()
        connection.close()
        # Verify cleanup on a new connection rather than trusting savepoints.
        try:
            with engine.connect() as check:
                assert check.execute(text("SELECT count(*) FROM companies WHERE slug = :slug"), {"slug": slug}).scalar_one() == 0
        finally:
            engine.dispose()
