from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
import csv, io, json, pandas as pd
from ..database import get_db
from ..models.user import User
from ..models.client import Client
from ..core.permissions import get_current_user

router = APIRouter(prefix="/import-export", tags=["import-export"])

@router.post("/clients/preview")
async def preview_clients(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    content = await file.read()
    filename = file.filename or ""
    rows = []
    errors = []
    try:
        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            df = pd.read_excel(io.BytesIO(content))
            # normalize columns
            df.columns = [c.strip().lower() for c in df.columns]
            # map possible french headers to expected
            col_map = {
                "société": "company_name", "societe": "company_name", "entreprise": "company_name", "nom": "company_name", "company_name": "company_name",
                "email": "email", "e-mail": "email",
                "téléphone": "phone", "telephone": "phone", "phone": "phone",
                "ville": "city", "city": "city",
                "secteur": "sector", "sector": "sector",
                "source": "source",
                "type": "type", "statut": "status", "status": "status",
                "adresse": "address", "address": "address",
                "site web": "website", "website": "website",
                "contact": "first_name",
            }
            # try to rename
            new_cols = {}
            for c in df.columns:
                if c in col_map:
                    new_cols[c] = col_map[c]
                else:
                    new_cols[c] = c
            df.rename(columns=new_cols, inplace=True)
            for idx, row in df.iterrows():
                r = {k: (None if pd.isna(v) else str(v).strip()) for k, v in row.items()}
                # validation
                if not r.get("company_name"):
                    errors.append({"row": idx+2, "error": "Nom d'entreprise manquant"})
                else:
                    rows.append(r)
        else:
            # CSV
            text = content.decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(text))
            for idx, row in enumerate(reader, start=2):
                # normalize keys
                norm = {k.strip().lower(): v for k,v in row.items()}
                r = {
                    "company_name": norm.get("company_name") or norm.get("société") or norm.get("societe") or norm.get("entreprise") or norm.get("nom"),
                    "email": norm.get("email"),
                    "phone": norm.get("phone") or norm.get("téléphone") or norm.get("telephone"),
                    "city": norm.get("city") or norm.get("ville"),
                    "sector": norm.get("sector") or norm.get("secteur"),
                    "source": norm.get("source"),
                    "type": norm.get("type") or "prospect",
                    "address": norm.get("address") or norm.get("adresse"),
                }
                if not r["company_name"]:
                    errors.append({"row": idx, "error": "Nom d'entreprise manquant"})
                else:
                    rows.append(r)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erreur de lecture du fichier: {str(e)}")
    
    return {"preview": rows[:20], "total_rows": len(rows), "errors": errors[:20], "total_errors": len(errors), "columns_detected": list(rows[0].keys()) if rows else []}

@router.post("/clients/import")
async def import_clients(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    content = await file.read()
    filename = file.filename or ""
    imported = 0
    errors = []
    try:
        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            df = pd.read_excel(io.BytesIO(content))
            df.columns = [c.strip().lower() for c in df.columns]
            col_map = {
                "société": "company_name", "societe": "company_name", "entreprise": "company_name", "nom": "company_name", "company_name": "company_name",
                "email": "email", "e-mail": "email",
                "téléphone": "phone", "telephone": "phone", "phone": "phone",
                "ville": "city", "city": "city",
                "secteur": "sector", "sector": "sector",
                "source": "source",
                "type": "type", "statut": "status", "status": "status",
                "adresse": "address", "address": "address",
                "site web": "website", "website": "website",
            }
            df.rename(columns={c: col_map.get(c, c) for c in df.columns}, inplace=True)
            for idx, row in df.iterrows():
                try:
                    r = {k: (None if pd.isna(v) else str(v).strip()) for k, v in row.items()}
                    if not r.get("company_name"):
                        errors.append({"row": idx+2, "error": "Nom manquant"})
                        continue
                    client = Client(
                        company_id=current_user.company_id,
                        owner_id=current_user.id,
                        company_name=r.get("company_name"),
                        email=r.get("email"),
                        phone=r.get("phone"),
                        city=r.get("city"),
                        sector=r.get("sector"),
                        source=r.get("source"),
                        type=(r.get("type") or "prospect").lower(),
                        status=r.get("status") or "actif",
                        address=r.get("address"),
                        website=r.get("website"),
                        country="Tunisie"
                    )
                    db.add(client); imported += 1
                except Exception as e:
                    errors.append({"row": idx+2, "error": str(e)})
            db.commit()
        else:
            text = content.decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(text))
            for idx, row in enumerate(reader, start=2):
                norm = {k.strip().lower(): v for k,v in row.items()}
                company_name = norm.get("company_name") or norm.get("société") or norm.get("societe") or norm.get("entreprise") or norm.get("nom")
                if not company_name:
                    errors.append({"row": idx, "error": "Nom manquant"})
                    continue
                client = Client(
                    company_id=current_user.company_id,
                    owner_id=current_user.id,
                    company_name=company_name,
                    email=norm.get("email"),
                    phone=norm.get("phone") or norm.get("téléphone") or norm.get("telephone"),
                    city=norm.get("city") or norm.get("ville"),
                    sector=norm.get("sector") or norm.get("secteur"),
                    source=norm.get("source"),
                    type=(norm.get("type") or "prospect").lower(),
                    country="Tunisie"
                )
                db.add(client); imported += 1
            db.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"imported": imported, "errors": errors}

@router.get("/clients/export")
def export_clients(db: Session = Depends(get_db), current_user: User = Depends(get_current_user), format: str = Query("csv", regex="^(csv|excel)$"), type: Optional[str] = None):
    query = db.query(Client).filter(Client.company_id == current_user.company_id, Client.is_archived==False)
    if type:
        query = query.filter(Client.type == type)
    clients = query.all()
    
    if format == "excel":
        df = pd.DataFrame([{
            "Société": c.company_name,
            "Type": c.type,
            "Statut": c.status,
            "Email": c.email,
            "Téléphone": c.phone,
            "Ville": c.city,
            "Secteur": c.sector,
            "Source": c.source,
            "Adresse": c.address,
            "Site web": c.website,
            "Propriétaire ID": c.owner_id,
            "Créé le": c.created_at
        } for c in clients])
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="Clients")
        output.seek(0)
        return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition":"attachment; filename=clients.xlsx"})
    else:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["company_name","type","status","email","phone","city","sector","source","address","website"])
        for c in clients:
            writer.writerow([c.company_name, c.type, c.status, c.email, c.phone, c.city, c.sector, c.source, c.address, c.website])
        output.seek(0)
        return StreamingResponse(io.StringIO(output.getvalue()), media_type="text/csv", headers={"Content-Disposition":"attachment; filename=clients.csv"})
