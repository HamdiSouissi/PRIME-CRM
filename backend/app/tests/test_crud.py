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
    email = f"u{uuid.uuid4().hex[:6]}@test.tn"
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": "Test123!Test", "first_name": "U", "last_name": "Test", "company_name": f"C {email}"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]

def test_client_crud():
    token = get_token()
    h = {"Authorization": f"Bearer {token}"}
    # create
    resp = client.post("/api/v1/clients", json={"company_name": "Acme Tun", "email": "acme@tun.tn", "city": "Tunis", "sector": "Technologie"}, headers=h)
    assert resp.status_code == 200, resp.text
    cid = resp.json()["id"]
    # get
    resp = client.get(f"/api/v1/clients/{cid}", headers=h)
    assert resp.status_code == 200
    assert resp.json()["company_name"] == "Acme Tun"
    # update
    resp = client.put(f"/api/v1/clients/{cid}", json={"city": "Sfax"}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["city"] == "Sfax"
    # list with search
    resp = client.get("/api/v1/clients?search=Acme", headers=h)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    # full
    resp = client.get(f"/api/v1/clients/{cid}/full", headers=h)
    assert resp.status_code == 200
    assert "contacts" in resp.json()

def test_pipeline():
    token = get_token()
    h = {"Authorization": f"Bearer {token}"}
    # get stages
    resp = client.get("/api/v1/stages", headers=h)
    assert resp.status_code == 200
    stages = resp.json()
    assert len(stages) >= 5
    first_stage = stages[0]
    # create client
    resp = client.post("/api/v1/clients", json={"company_name": "Client Pipeline"}, headers=h)
    cid = resp.json()["id"]
    # create opportunity
    resp = client.post("/api/v1/opportunities", json={"client_id": cid, "stage_id": first_stage["id"], "title": "Deal test", "amount": 5000, "probability": 50}, headers=h)
    assert resp.status_code == 200, resp.text
    oid = resp.json()["id"]
    assert resp.json()["weighted_amount"] == 2500
    # move
    second_stage = stages[1]
    resp = client.post(f"/api/v1/opportunities/{oid}/move", json={"stage_id": second_stage["id"]}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["stage_id"] == second_stage["id"]
    # pipeline endpoint
    resp = client.get("/api/v1/opportunities/pipeline", headers=h)
    assert resp.status_code == 200
    assert "total_value" in resp.json()

def test_quote_pdf_calculations():
    token = get_token()
    h = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/v1/clients", json={"company_name": "Client Devis"}, headers=h)
    cid = resp.json()["id"]
    # create product
    resp = client.post("/api/v1/products", json={"name": "Service Dev", "price": 1000, "tax_rate": 19}, headers=h)
    assert resp.status_code == 200
    # create quote
    resp = client.post("/api/v1/quotes", json={
        "client_id": cid,
        "title": "Devis test",
        "currency": "TND",
        "lines": [
            {"name": "Service Dev", "quantity": 2, "unit_price": 1000, "tax_rate": 19},
            {"name": "Licence", "quantity": 1, "unit_price": 500, "discount_percent": 10, "tax_rate": 19}
        ]
    }, headers=h)
    assert resp.status_code == 200, resp.text
    qid = resp.json()["id"]
    # expected: line1 2000 HT + 380 TVA = 2380 TTC
    # line2: 500*0.9=450 HT +85.5 TVA=535.5
    # subtotal 2450, tax 465.5, total 2915.5
    assert resp.json()["subtotal"] == 2450
    assert abs(resp.json()["total"] - 2915.5) < 0.01
    # PDF
    resp = client.get(f"/api/v1/quotes/{qid}/pdf", headers=h)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert len(resp.content) > 1000

def test_opportunity_loss_reason_required():
    token = get_token()
    h = {"Authorization": f"Bearer {token}"}
    stages = client.get("/api/v1/stages", headers=h).json()
    lost_stage = next(s for s in stages if s["is_lost"])
    resp = client.post("/api/v1/clients", json={"company_name": "Client Perdu"}, headers=h)
    cid = resp.json()["id"]
    resp = client.post("/api/v1/opportunities", json={"client_id": cid, "stage_id": stages[0]["id"], "title": "Affaire perdue", "amount": 1000}, headers=h)
    oid = resp.json()["id"]
    # try move to lost without reason -> 400
    resp = client.post(f"/api/v1/opportunities/{oid}/move", json={"stage_id": lost_stage["id"]}, headers=h)
    assert resp.status_code == 400
    # with reason -> ok
    resp = client.post(f"/api/v1/opportunities/{oid}/move", json={"stage_id": lost_stage["id"], "loss_reason": "Prix trop élevé"}, headers=h)
    assert resp.status_code == 200

def test_import_export():
    import io
    token = get_token()
    h = {"Authorization": f"Bearer {token}"}
    csv_content = "company_name,email,phone,city\nTestImport,test@import.tn,+21612345678,Tunis\n"
    files = {"file": ("test.csv", csv_content, "text/csv")}
    resp = client.post("/api/v1/import-export/clients/preview", files=files, headers=h)
    assert resp.status_code == 200
    assert resp.json()["total_rows"] == 1
    resp = client.post("/api/v1/import-export/clients/import", files=files, headers=h)
    assert resp.status_code == 200
    assert resp.json()["imported"] == 1
    resp = client.get("/api/v1/import-export/clients/export?format=csv", headers=h)
    assert resp.status_code == 200
    assert "company_name" in resp.text
