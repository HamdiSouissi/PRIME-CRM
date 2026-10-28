import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Use in-memory SQLite for tests
TEST_DB_URL = "sqlite:///:memory:"

import os
os.environ["DATABASE_URL"] = TEST_DB_URL

from app.database import Base, get_db
from app.main import app
from app.models.company import Company
from app.models.user import User

engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
Base.metadata.create_all(bind=engine)
client = TestClient(app)

def test_register_and_login():
    # Register new company/admin
    resp = client.post("/api/v1/auth/register", json={
        "email": "test@prime.tn",
        "password": "Test123!Test",
        "first_name": "Test",
        "last_name": "User",
        "company_name": "Test Company"
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    token = data["access_token"]
    
    # Me
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "test@prime.tn"
    
    # Login json
    resp = client.post("/api/v1/auth/login-json", json={"email": "test@prime.tn", "password": "Test123!Test"})
    assert resp.status_code == 200
    assert resp.json()["access_token"]

def test_company_isolation():
    # Create second company
    resp1 = client.post("/api/v1/auth/register", json={
        "email": "alice@societe-a.tn", "password": "Test123!Test", "first_name": "Alice", "last_name": "A", "company_name": "Societe A"
    })
    token_a = resp1.json()["access_token"]
    resp2 = client.post("/api/v1/auth/register", json={
        "email": "bob@societe-b.tn", "password": "Test123!Test", "first_name": "Bob", "last_name": "B", "company_name": "Societe B"
    })
    token_b = resp2.json()["access_token"]
    
    # Alice creates client
    resp = client.post("/api/v1/clients", json={"company_name": "Client A", "email": "client@a.tn"}, headers={"Authorization": f"Bearer {token_a}"})
    assert resp.status_code == 200
    client_id = resp.json()["id"]
    
    # Bob should not see it
    resp = client.get(f"/api/v1/clients/{client_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert resp.status_code == 404
    
    # Bob list should be empty (or not contain this)
    resp = client.get("/api/v1/clients", headers={"Authorization": f"Bearer {token_b}"})
    ids = [c["id"] for c in resp.json()["items"]]
    assert client_id not in ids
