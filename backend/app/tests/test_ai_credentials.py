"""AI credential tests: disposable SQLite, fictitious keys, no external HTTP."""

import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.core.security import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models.ai_provider import AIProviderConfig
from app.models.company import Company
from app.models.user import User
from app.services.ai_service import egress
from app.services.ai_service.credentials import (
    AICredentialError,
    CREDENTIAL_PREFIX,
    decrypt_credential,
    encrypt_credential,
)


TEST_SIGNING_KEY = "only-a-fictitious-test-secret-with-sufficient-length-123"
TEST_API_KEY = "sk-fake-provider-key-abcdef123456789"
OTHER_API_KEY = "sk-fake-provider-key-xyz987654321"
PROVIDER_URL = "https://provider.example.invalid/v1"


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", TEST_SIGNING_KEY)
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(settings, "AI_ALLOWED_ORIGINS", "https://provider.example.invalid,https://attacker.example.invalid,https://ollama.example.invalid:11434")

    async def fake_resolve(target):
        assert target.hostname in {"provider.example.invalid", "attacker.example.invalid", "ollama.example.invalid"}
        return ["93.184.216.34"]

    monkeypatch.setattr(egress, "_resolve_ipv4", fake_resolve)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with factory() as db:
        first = Company(name="Test One", slug="one")
        second = Company(name="Test Two", slug="two")
        db.add_all([first, second])
        db.flush()
        users = [
            User(email="admin@example.test", first_name="Test", last_name="Admin", hashed_password="unused", role="admin", company_id=first.id),
            User(email="viewer@example.test", first_name="Test", last_name="Viewer", hashed_password="unused", role="viewer", company_id=first.id),
            User(email="other@example.test", first_name="Other", last_name="Admin", hashed_password="unused", role="admin", company_id=second.id),
        ]
        db.add_all(users)
        db.flush()
        identities = [(user.id, user.session_nonce) for user in users]
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    # These tests replace all outbound async HTTP with a MockTransport. No
    # external AI provider, Redis or PostgreSQL connection can be made.
    outbound = []
    handler = {"fn": lambda request: httpx.Response(200, json={"data": []})}
    real_async_client = httpx.AsyncClient

    def mock_async_client(*args, **kwargs):
        def route(request):
            outbound.append(request)
            return handler["fn"](request)
        kwargs["transport"] = httpx.MockTransport(route)
        kwargs["trust_env"] = False
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_async_client)
    old_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_db
    headers = [
        {"Authorization": f"Bearer {create_access_token(user_id, session_nonce=nonce)}"}
        for user_id, nonce in identities
    ]
    client = TestClient(app)
    yield {"client": client, "factory": factory, "admin": headers[0], "viewer": headers[1], "other": headers[2], "outbound": outbound, "handler": handler}
    client.close()
    app.dependency_overrides.clear()
    app.dependency_overrides.update(old_overrides)
    engine.dispose()


def create_provider(harness, *, api_key=TEST_API_KEY, base_url=PROVIDER_URL):
    response = harness["client"].post("/api/v1/ai/providers", headers=harness["admin"], json={
        "provider": "openai_compat",
        "name": "Fake provider",
        "api_base_url": base_url,
        "api_key": api_key,
        "model_id": "dummy-model",
        "is_active": True,
        "is_default": True,
    })
    assert response.status_code == 200, response.text
    return response


def test_new_credentials_are_encrypted_randomized_and_bound_to_record(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", TEST_SIGNING_KEY)
    first = encrypt_credential(TEST_API_KEY, 7, 12)
    second = encrypt_credential(TEST_API_KEY, 7, 12)
    assert first.startswith(CREDENTIAL_PREFIX)
    assert TEST_API_KEY not in first
    assert first != second
    assert decrypt_credential(first, 7, 12) == TEST_API_KEY
    for company_id, provider_id in [(8, 12), (7, 13)]:
        with pytest.raises(AICredentialError) as result:
            decrypt_credential(first, company_id, provider_id)
        assert TEST_API_KEY not in str(result.value)
    token = first[len(CREDENTIAL_PREFIX):]
    pos = len(token) // 2
    tampered = CREDENTIAL_PREFIX + token[:pos] + ("A" if token[pos] != "A" else "B") + token[pos+1:]
    with pytest.raises(AICredentialError):
        decrypt_credential(tampered, 7, 12)
    with pytest.raises(AICredentialError):
        decrypt_credential(first + "!", 7, 12)
    monkeypatch.setattr(settings, "SECRET_KEY", "another-fictitious-signing-key-with-sufficient-entropy-456")
    with pytest.raises(AICredentialError):
        decrypt_credential(first, 7, 12)


def test_crud_stores_only_ciphertext_and_never_returns_key_fragments(harness):
    response = create_provider(harness)
    provider_id = response.json()["id"]
    assert response.json()["api_key_masked"] == "***"
    assert response.json()["api_key_needs_reset"] is False
    assert TEST_API_KEY not in response.text
    assert TEST_API_KEY[:8] not in response.text
    with harness["factory"]() as db:
        cfg = db.get(AIProviderConfig, provider_id)
        stored = cfg.api_key_encrypted
        assert stored.startswith(CREDENTIAL_PREFIX)
        assert TEST_API_KEY not in stored
        assert decrypt_credential(stored, cfg.company_id, cfg.id) == TEST_API_KEY

    response = harness["client"].get("/api/v1/ai/providers", headers=harness["admin"])
    assert response.status_code == 200
    assert TEST_API_KEY not in response.text and TEST_API_KEY[:8] not in response.text
    assert response.json()[0]["api_key_masked"] == "***"
    assert harness["client"].get("/api/v1/ai/providers", headers=harness["other"]).json() == []
    assert harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["other"], json={"api_key": OTHER_API_KEY}).status_code == 404
    assert harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["viewer"], json={"api_key": OTHER_API_KEY}).status_code == 403

    # Editing non-secret settings does not change the ciphertext.
    assert harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={"name": "Renamed"}).status_code == 200
    with harness["factory"]() as db:
        assert db.get(AIProviderConfig, provider_id).api_key_encrypted == stored

    response = harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={"api_key": OTHER_API_KEY})
    assert response.status_code == 200
    assert OTHER_API_KEY not in response.text
    with harness["factory"]() as db:
        cfg = db.get(AIProviderConfig, provider_id)
        assert cfg.api_key_encrypted != stored
        assert OTHER_API_KEY not in cfg.api_key_encrypted
        assert decrypt_credential(cfg.api_key_encrypted, cfg.company_id, cfg.id) == OTHER_API_KEY

    response = harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={"api_key": None})
    assert response.status_code == 200
    assert response.json()["api_key_masked"] is None
    with harness["factory"]() as db:
        assert db.get(AIProviderConfig, provider_id).api_key_encrypted is None


def test_provider_test_models_and_generate_use_decrypted_key_only_for_request(harness, caplog):
    response = create_provider(harness)
    provider_id = response.json()["id"]

    def provider(request):
        if request.url.path.endswith("/models"):
            # Even a badly behaved provider must not reflect a credential as a model ID.
            return httpx.Response(200, json={"data": [{"id": "test-model"}, {"id": "echo-" + TEST_API_KEY}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Réponse simulée"}}]})

    harness["handler"]["fn"] = provider
    with caplog.at_level(logging.INFO):
        tested = harness["client"].post("/api/v1/ai/providers/test", headers=harness["admin"], json={"provider_id": provider_id})
        models = harness["client"].get(f"/api/v1/ai/providers/{provider_id}/models", headers=harness["admin"])
        generated = harness["client"].post("/api/v1/ai/generate", headers=harness["viewer"], json={"prompt": "Bonjour", "provider_id": provider_id})
    assert tested.status_code == 200 and tested.json()["success"] is True
    assert tested.json()["models"] == ["test-model"]
    assert models.status_code == 200 and models.json() == {"models": ["test-model"]}
    assert generated.status_code == 200 and generated.json()["content"] == "Réponse simulée"
    assert len(harness["outbound"]) == 3
    assert all(req.headers["authorization"] == f"Bearer {TEST_API_KEY}" for req in harness["outbound"])
    assert all(req.url.host == "93.184.216.34" and req.url.path.startswith("/v1/") for req in harness["outbound"])
    assert all(req.headers["host"] == "provider.example.invalid" for req in harness["outbound"])
    assert all(req.extensions["sni_hostname"] == "provider.example.invalid" for req in harness["outbound"])
    assert TEST_API_KEY not in tested.text + models.text + generated.text + caplog.text


def test_non_admin_and_url_overrides_cannot_exfiltrate_saved_credential(harness):
    provider_id = create_provider(harness).json()["id"]
    endpoint = "/api/v1/ai/providers/test"
    payload = {"provider_id": provider_id, "api_base_url": "https://attacker.example.invalid"}
    assert harness["client"].post(endpoint, headers=harness["viewer"], json=payload).status_code == 403
    assert harness["client"].get(f"/api/v1/ai/providers/{provider_id}/models", headers=harness["viewer"]).status_code == 403
    assert harness["client"].post(endpoint, headers=harness["admin"], json=payload).status_code == 400
    assert harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={"api_base_url": payload["api_base_url"]}).status_code == 400
    with harness["factory"]() as db:
        cfg = db.get(AIProviderConfig, provider_id)
        assert cfg.api_base_url == PROVIDER_URL
        assert decrypt_credential(cfg.api_key_encrypted, cfg.company_id, cfg.id) == TEST_API_KEY
    assert harness["outbound"] == []

    # Moving to a different URL requires supplying a replacement or explicitly
    # clearing the saved credential in the same update.
    updated = harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={"api_base_url": payload["api_base_url"], "api_key": None})
    assert updated.status_code == 200
    assert updated.json()["api_key_masked"] is None
    assert harness["outbound"] == []


@pytest.mark.parametrize("legacy_value", [TEST_API_KEY, CREDENTIAL_PREFIX + "not-valid-ciphertext"])
def test_legacy_or_corrupted_keys_are_not_sent_and_must_be_replaced(harness, legacy_value):
    provider_id = create_provider(harness).json()["id"]
    with harness["factory"]() as db:
        cfg = db.get(AIProviderConfig, provider_id)
        cfg.api_key_encrypted = legacy_value
        cfg.last_test_status = "failed"
        cfg.last_test_message = "Old upstream error: " + TEST_API_KEY
        db.commit()
    listed = harness["client"].get("/api/v1/ai/providers", headers=harness["admin"])
    assert listed.json()[0]["api_key_needs_reset"] is True
    assert listed.json()[0]["api_key_masked"] == "***"
    assert TEST_API_KEY not in listed.text and legacy_value not in listed.text
    tested = harness["client"].post("/api/v1/ai/providers/test", headers=harness["admin"], json={"provider_id": provider_id})
    models = harness["client"].get(f"/api/v1/ai/providers/{provider_id}/models", headers=harness["admin"])
    generated = harness["client"].post("/api/v1/ai/generate", headers=harness["admin"], json={"prompt": "Bonjour", "provider_id": provider_id})
    assert tested.status_code == 200 and tested.json()["success"] is False
    assert models.status_code == 400 and generated.status_code == 400
    assert TEST_API_KEY not in tested.text + models.text + generated.text
    assert harness["outbound"] == []

    replaced = harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={"api_key": OTHER_API_KEY})
    assert replaced.status_code == 200 and replaced.json()["api_key_needs_reset"] is False
    with harness["factory"]() as db:
        cfg = db.get(AIProviderConfig, provider_id)
        assert decrypt_credential(cfg.api_key_encrypted, cfg.company_id, cfg.id) == OTHER_API_KEY
        assert cfg.last_test_message is None


def test_upstream_error_bodies_and_exception_messages_are_not_exposed_or_stored(harness, caplog):
    provider_id = create_provider(harness).json()["id"]
    harness["handler"]["fn"] = lambda request: httpx.Response(401, text="bad provider response " + TEST_API_KEY)
    with caplog.at_level(logging.INFO):
        tested = harness["client"].post("/api/v1/ai/providers/test", headers=harness["admin"], json={"provider_id": provider_id})
        models = harness["client"].get(f"/api/v1/ai/providers/{provider_id}/models", headers=harness["admin"])
        generated = harness["client"].post("/api/v1/ai/generate", headers=harness["admin"], json={"prompt": "Bonjour", "provider_id": provider_id})
    assert tested.json()["success"] is False and "401" in tested.json()["message"]
    assert models.status_code == 400 and generated.status_code == 400
    assert TEST_API_KEY not in tested.text + models.text + generated.text + caplog.text
    with harness["factory"]() as db:
        assert TEST_API_KEY not in db.get(AIProviderConfig, provider_id).last_test_message

    def broken(request):
        raise httpx.ConnectError("Simulated exception containing " + TEST_API_KEY, request=request)
    harness["handler"]["fn"] = broken
    response = harness["client"].post("/api/v1/ai/providers/test", headers=harness["admin"], json={"provider_id": provider_id})
    assert response.json()["success"] is False
    assert TEST_API_KEY not in response.text
    with harness["factory"]() as db:
        assert TEST_API_KEY not in db.get(AIProviderConfig, provider_id).last_test_message


def test_legacy_url_credentials_are_not_returned(harness):
    provider_id = create_provider(harness).json()["id"]
    with harness["factory"]() as db:
        cfg = db.get(AIProviderConfig, provider_id)
        cfg.api_base_url = "https://user:fake-url-password@provider.example.invalid/v1?key=fake-query-token"
        db.commit()
    listed = harness["client"].get("/api/v1/ai/providers", headers=harness["admin"])
    assert listed.status_code == 200
    assert listed.json()[0]["api_base_url"] is None
    assert "fake-url-password" not in listed.text and "fake-query-token" not in listed.text


@pytest.mark.parametrize("url", [
    "http://provider.example.invalid/v1",
    "https://user:fake-password@provider.example.invalid/v1",
    "https://provider.example.invalid/v1?key=fake-token",
    "https://provider.example.invalid/v1#fragment",
    "https://provider.example.invalid:invalid/v1",
    "https://provider.example.invalid\\@attacker.example.invalid/v1",
])
def test_production_rejects_insecure_provider_urls_without_echoing_them(harness, monkeypatch, url):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    response = harness["client"].post("/api/v1/ai/providers", headers=harness["admin"], json={
        "provider": "openai_compat", "name": "Fake", "api_base_url": url, "api_key": TEST_API_KEY,
    })
    assert response.status_code == 400
    assert url not in response.text and TEST_API_KEY not in response.text
    assert harness["outbound"] == []


def test_old_insecure_url_can_be_repaired_with_new_key(harness, monkeypatch):
    provider_id = create_provider(harness).json()["id"]
    with harness["factory"]() as db:
        cfg = db.get(AIProviderConfig, provider_id)
        cfg.api_base_url = "http://legacy.example.invalid/v1"
        cfg.api_key_encrypted = TEST_API_KEY
        db.commit()
    monkeypatch.setattr(settings, "APP_ENV", "production")
    response = harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={"api_base_url": PROVIDER_URL, "api_key": OTHER_API_KEY})
    assert response.status_code == 200
    assert response.json()["api_key_needs_reset"] is False
    assert TEST_API_KEY not in response.text and OTHER_API_KEY not in response.text
    assert harness["outbound"] == []


def test_unsaved_provider_test_uses_only_the_supplied_fictitious_credential(harness):
    harness["handler"]["fn"] = lambda request: httpx.Response(200, json={"data": [{"id": "temporary-model"}]})
    tested = harness["client"].post("/api/v1/ai/providers/test", headers=harness["admin"], json={
        "provider": "openai_compat", "api_base_url": PROVIDER_URL, "api_key": OTHER_API_KEY,
    })
    assert tested.status_code == 200 and tested.json()["models"] == ["temporary-model"]
    assert OTHER_API_KEY not in tested.text
    assert len(harness["outbound"]) == 1
    assert harness["outbound"][0].headers["authorization"] == f"Bearer {OTHER_API_KEY}"
    with harness["factory"]() as db:
        assert db.query(AIProviderConfig).count() == 0


def test_ollama_test_models_and_generation_remain_available_with_mock_transport(harness):
    response = harness["client"].post("/api/v1/ai/providers", headers=harness["admin"], json={
        "provider": "ollama", "name": "Fake HTTPS Ollama", "is_active": True,
        "ollama_url": "https://ollama.example.invalid:11434", "ollama_model": "fake-local-model",
    })
    assert response.status_code == 200
    provider_id = response.json()["id"]

    def ollama(request):
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": "fake-local-model"}]})
        return httpx.Response(200, json={"response": "Réponse locale simulée"})

    harness["handler"]["fn"] = ollama
    tested = harness["client"].post("/api/v1/ai/providers/test", headers=harness["admin"], json={"provider_id": provider_id})
    models = harness["client"].get(f"/api/v1/ai/providers/{provider_id}/models", headers=harness["admin"])
    generated = harness["client"].post("/api/v1/ai/generate", headers=harness["viewer"], json={"prompt": "Bonjour", "provider_id": provider_id})
    assert tested.status_code == 200 and tested.json()["models"] == ["fake-local-model"]
    assert models.status_code == 200 and models.json()["models"] == ["fake-local-model"]
    assert generated.status_code == 200 and generated.json()["content"] == "Réponse locale simulée"
    assert len(harness["outbound"]) == 3
    assert all("authorization" not in req.headers for req in harness["outbound"])


def test_invalid_credential_rolls_back_new_provider_and_default_change(harness):
    provider_id = create_provider(harness).json()["id"]
    bad = harness["client"].post("/api/v1/ai/providers", headers=harness["admin"], json={
        "provider": "openai_compat", "name": "Invalid", "is_default": True,
        "api_base_url": PROVIDER_URL, "api_key": "\ud800",
    })
    assert bad.status_code == 400
    assert "Clé IA invalide" in bad.text
    with harness["factory"]() as db:
        providers = db.query(AIProviderConfig).all()
        assert len(providers) == 1 and providers[0].id == provider_id
        assert providers[0].is_default is True


@pytest.mark.parametrize("legacy_url", [
    "http://169.254.169.254/latest/meta-data",
    "https://unapproved.example.invalid/v1",
    "https://user:old-fake-password@provider.example.invalid/v1?secret=old-fake-token",
])
def test_legacy_openai_destinations_block_every_action_but_can_be_disabled_or_repaired(harness, monkeypatch, legacy_url):
    provider_id = create_provider(harness).json()["id"]
    with harness["factory"]() as db:
        db.get(AIProviderConfig, provider_id).api_base_url = legacy_url
        db.commit()
    monkeypatch.setattr(settings, "APP_ENV", "production")
    tested = harness["client"].post("/api/v1/ai/providers/test", headers=harness["admin"], json={"provider_id": provider_id})
    models = harness["client"].get(f"/api/v1/ai/providers/{provider_id}/models", headers=harness["admin"])
    generated = harness["client"].post("/api/v1/ai/generate", headers=harness["viewer"], json={"prompt": "Hi", "provider_id": provider_id})
    assert tested.status_code == models.status_code == generated.status_code == 400
    assert TEST_API_KEY not in tested.text + models.text + generated.text
    assert legacy_url not in tested.text + models.text + generated.text
    assert harness["outbound"] == []

    disabled = harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={"is_active": False})
    assert disabled.status_code == 200 and disabled.json()["is_active"] is False
    denied_enable = harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={"is_active": True})
    assert denied_enable.status_code == 400
    repaired = harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={
        "api_base_url": PROVIDER_URL, "api_key": OTHER_API_KEY, "is_active": True,
    })
    assert repaired.status_code == 200 and repaired.json()["is_active"] is True
    assert TEST_API_KEY not in repaired.text and OTHER_API_KEY not in repaired.text
    assert harness["outbound"] == []


def test_legacy_ollama_destination_blocked_everywhere_but_can_be_disabled_or_repaired(harness, monkeypatch):
    created = harness["client"].post("/api/v1/ai/providers", headers=harness["admin"], json={
        "provider": "ollama", "name": "Legacy fake", "is_active": True,
        "ollama_url": "https://ollama.example.invalid:11434", "ollama_model": "test-model",
    })
    assert created.status_code == 200
    provider_id = created.json()["id"]
    with harness["factory"]() as db:
        db.get(AIProviderConfig, provider_id).ollama_url = "http://169.254.169.254:11434"
        db.commit()
    monkeypatch.setattr(settings, "APP_ENV", "production")
    tested = harness["client"].post("/api/v1/ai/providers/test", headers=harness["admin"], json={"provider_id": provider_id})
    models = harness["client"].get(f"/api/v1/ai/providers/{provider_id}/models", headers=harness["admin"])
    generated = harness["client"].post("/api/v1/ai/generate", headers=harness["viewer"], json={"prompt": "Hi", "provider_id": provider_id})
    assert tested.status_code == models.status_code == generated.status_code == 400
    assert harness["outbound"] == []
    disabled = harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={"is_active": False})
    assert disabled.status_code == 200
    assert harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={"is_active": True}).status_code == 400
    repaired = harness["client"].put(f"/api/v1/ai/providers/{provider_id}", headers=harness["admin"], json={
        "ollama_url": "https://ollama.example.invalid:11434", "is_active": True,
    })
    assert repaired.status_code == 200 and repaired.json()["is_active"] is True
    assert harness["outbound"] == []


def test_removing_origin_immediately_blocks_saved_provider_without_sending_key(harness, monkeypatch):
    provider_id = create_provider(harness).json()["id"]
    monkeypatch.setattr(settings, "AI_ALLOWED_ORIGINS", "")
    tested = harness["client"].post("/api/v1/ai/providers/test", headers=harness["admin"], json={"provider_id": provider_id})
    models = harness["client"].get(f"/api/v1/ai/providers/{provider_id}/models", headers=harness["admin"])
    generated = harness["client"].post("/api/v1/ai/generate", headers=harness["viewer"], json={"prompt": "Hi", "provider_id": provider_id})
    assert tested.status_code == models.status_code == generated.status_code == 400
    assert TEST_API_KEY not in tested.text + models.text + generated.text
    assert harness["outbound"] == []


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["169.254.169.254"], ["93.184.216.34", "10.0.0.1"]])
def test_allowed_origin_with_private_or_mixed_dns_is_blocked_in_every_api_path(harness, monkeypatch, addresses):
    provider_id = create_provider(harness).json()["id"]

    async def unsafe_dns(target):
        return addresses

    monkeypatch.setattr(egress, "_resolve_ipv4", unsafe_dns)
    tested = harness["client"].post("/api/v1/ai/providers/test", headers=harness["admin"], json={"provider_id": provider_id})
    models = harness["client"].get(f"/api/v1/ai/providers/{provider_id}/models", headers=harness["admin"])
    generated = harness["client"].post("/api/v1/ai/generate", headers=harness["viewer"], json={"prompt": "Hi", "provider_id": provider_id})
    assert tested.status_code == models.status_code == generated.status_code == 400
    assert TEST_API_KEY not in tested.text + models.text + generated.text
    assert all(address not in tested.text + models.text + generated.text for address in addresses)
    assert harness["outbound"] == []


def test_ai_request_validation_never_reflects_credentials(harness):
    provider_id = create_provider(harness).json()["id"]
    attempts = [
        ("post", "/api/v1/ai/providers", {"provider": "openai_compat", "api_key": TEST_API_KEY}),
        ("post", "/api/v1/ai/providers/test", {"provider_id": "not-an-integer", "api_key": TEST_API_KEY}),
        ("put", f"/api/v1/ai/providers/{provider_id}", {"temperature": "not-a-number", "api_key": TEST_API_KEY}),
        ("post", "/api/v1/ai/generate", {"prompt": {"secret": TEST_API_KEY}}),
    ]
    for method, path, payload in attempts:
        response = getattr(harness["client"], method)(path, headers=harness["admin"], json=payload)
        assert response.status_code == 422 and response.json() == {"detail": "Données invalides"}
        assert TEST_API_KEY not in response.text
    assert harness["outbound"] == []


def test_development_local_ollama_works_only_after_explicit_opt_in(harness, monkeypatch):
    local_url = "http://localhost:11434"
    payload = {"provider": "ollama", "name": "Local test", "ollama_url": local_url, "is_active": True}
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "AI_ALLOW_LOCAL_OLLAMA", False)
    assert harness["client"].post("/api/v1/ai/providers", headers=harness["admin"], json=payload).status_code == 400
    monkeypatch.setattr(settings, "AI_ALLOW_LOCAL_OLLAMA", True)

    async def local_dns(target):
        assert target.hostname == "localhost" and target.local_ollama
        return ["127.0.0.1"]

    monkeypatch.setattr(egress, "_resolve_ipv4", local_dns)
    harness["handler"]["fn"] = lambda request: httpx.Response(200, json={"models": [{"name": "local-test"}]})
    created = harness["client"].post("/api/v1/ai/providers", headers=harness["admin"], json=payload)
    assert created.status_code == 200
    tested = harness["client"].post("/api/v1/ai/providers/test", headers=harness["admin"], json={"provider_id": created.json()["id"]})
    assert tested.status_code == 200 and tested.json()["models"] == ["local-test"]
    request = harness["outbound"][0]
    assert request.url.host == "127.0.0.1" and request.headers["host"] == "localhost:11434"
    assert "authorization" not in request.headers
    monkeypatch.setattr(settings, "APP_ENV", "production")
    assert harness["client"].post("/api/v1/ai/providers/test", headers=harness["admin"], json={"provider_id": created.json()["id"]}).status_code == 400
    assert len(harness["outbound"]) == 1
