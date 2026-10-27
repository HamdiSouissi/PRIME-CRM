from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
from app.database import Base, get_db
from app.main import app

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
def override_get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
app.dependency_overrides[get_db] = override_get_db
Base.metadata.create_all(bind=engine)
client = TestClient(app)

def get_token():
    import uuid
    email = f"ai{uuid.uuid4().hex[:6]}@test.tn"
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": "Test123!Test", "first_name": "AI", "last_name": "Test", "company_name": f"AI Corp {email}"})
    return resp.json()["access_token"]

def test_ai_provider_crud():
    token = get_token()
    h = {"Authorization": f"Bearer {token}"}
    # create ollama provider
    resp = client.post("/api/v1/ai/providers", json={
        "provider": "ollama",
        "name": "Ollama Local",
        "is_active": True,
        "is_default": True,
        "ollama_url": "http://host.docker.internal:11434",
        "ollama_model": "llama3.2",
        "temperature": 0.7
    }, headers=h)
    assert resp.status_code == 200, resp.text
    pid = resp.json()["id"]
    assert resp.json()["api_key_masked"] is None
    # list
    resp = client.get("/api/v1/ai/providers", headers=h)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
    # create codecraft
    resp = client.post("/api/v1/ai/providers", json={
        "provider": "codecraftapi",
        "name": "CodeCraft",
        "is_active": False,
        "api_base_url": "https://www.codecraftapi.com/v1",
        "api_key": "sk-test-123456789",
        "model_id": "gpt-4o-mini"
    }, headers=h)
    assert resp.status_code == 200
    assert resp.json()["api_key_masked"] == "sk-t***6789"
    # update
    resp = client.put(f"/api/v1/ai/providers/{pid}", json={"is_active": False}, headers=h)
    assert resp.status_code == 200
    # delete second
    cid = resp.json()["id"]
    # get one of them
    # test health (should not require external)
    resp = client.get("/api/v1/ai/health", headers=h)
    assert resp.status_code == 200
    assert resp.json()["fallback_available"] == True

def test_ai_no_provider_fallback():
    token = get_token()
    h = {"Authorization": f"Bearer {token}"}
    # without provider, summary should fallback to rule-based, not error 500
    # create client
    resp = client.post("/api/v1/clients", json={"company_name": "Client IA"}, headers=h)
    cid = resp.json()["id"]
    resp = client.post("/api/v1/ai/summary/client", json={"client_id": cid}, headers=h)
    # should return 200 with fallback content
    assert resp.status_code == 200
    assert "fallback" in resp.json()["provider"] or "Prime CRM" in resp.json()["content"]

def test_core_still_works_without_ai():
    token = get_token()
    h = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/dashboard", headers=h)
    assert resp.status_code == 200
    assert "stats" in resp.json()
