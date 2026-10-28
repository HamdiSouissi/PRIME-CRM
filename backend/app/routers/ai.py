from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import json, time, httpx
from datetime import datetime, timezone
from ..database import get_db
from ..models.user import User
from ..models.client import Client
from ..models.opportunity import Opportunity
from ..models.ai_provider import AIProviderConfig
from ..models.activity import Activity
from ..core.permissions import get_current_user, require_admin
from ..schemas.ai import AIProviderCreate, AIProviderUpdate, AIProviderResponse, AITestRequest, AITestResponse, AIGenerateRequest, AIGenerateResponse, AISummaryRequest, AIExtractRequest
from ..services.ai_service.manager import AIServiceManager

router = APIRouter(prefix="/ai", tags=["ai"])

def mask_key(key: str) -> str:
    if not key:
        return None
    if len(key) <= 8:
        return "***"
    return key[:4] + "***" + key[-4:]

def to_response(cfg: AIProviderConfig):
    return {
        "id": cfg.id,
        "company_id": cfg.company_id,
        "provider": cfg.provider,
        "name": cfg.name,
        "is_active": cfg.is_active,
        "is_default": cfg.is_default,
        "ollama_url": cfg.ollama_url,
        "ollama_model": cfg.ollama_model,
        "api_base_url": cfg.api_base_url,
        "api_key_masked": mask_key(cfg.api_key_encrypted),
        "model_id": cfg.model_id,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "timeout_seconds": cfg.timeout_seconds,
        "feature_mapping": json.loads(cfg.feature_mapping) if cfg.feature_mapping else None,
        "last_test_at": cfg.last_test_at,
        "last_test_status": cfg.last_test_status,
        "last_test_message": cfg.last_test_message,
        "created_at": cfg.created_at
    }

@router.get("/providers", response_model=List[AIProviderResponse])
def list_providers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    configs = db.query(AIProviderConfig).filter(AIProviderConfig.company_id == current_user.company_id).all()
    return [to_response(c) for c in configs]

@router.post("/providers", response_model=AIProviderResponse)
def create_provider(payload: AIProviderCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    # encrypt api_key simply (base64-like obscuring, in prod use proper encryption)
    api_key_encrypted = payload.api_key
    # if marking default, unset others
    if payload.is_default:
        db.query(AIProviderConfig).filter(AIProviderConfig.company_id==current_user.company_id).update({AIProviderConfig.is_default: False})
    
    cfg = AIProviderConfig(
        company_id=current_user.company_id,
        provider=payload.provider,
        name=payload.name,
        is_active=payload.is_active,
        is_default=payload.is_default,
        ollama_url=payload.ollama_url,
        ollama_model=payload.ollama_model,
        api_base_url=payload.api_base_url,
        api_key_encrypted=api_key_encrypted,
        model_id=payload.model_id,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        timeout_seconds=payload.timeout_seconds,
        feature_mapping=json.dumps(payload.feature_mapping) if payload.feature_mapping else None
    )
    db.add(cfg); db.commit(); db.refresh(cfg)
    return to_response(cfg)

@router.put("/providers/{provider_id}", response_model=AIProviderResponse)
def update_provider(provider_id: int, payload: AIProviderUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    cfg = db.query(AIProviderConfig).filter(AIProviderConfig.id==provider_id, AIProviderConfig.company_id==current_user.company_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Fournisseur non trouvé")
    
    data = payload.model_dump(exclude_unset=True)
    if "api_key" in data:
        cfg.api_key_encrypted = data.pop("api_key")
    if "feature_mapping" in data and data["feature_mapping"] is not None:
        cfg.feature_mapping = json.dumps(data.pop("feature_mapping"))
        # remaining fields
    for k, v in data.items():
        if k in ["feature_mapping"]:
            continue
        setattr(cfg, k, v)
    
    if payload.is_default:
        db.query(AIProviderConfig).filter(AIProviderConfig.company_id==current_user.company_id, AIProviderConfig.id!=cfg.id).update({AIProviderConfig.is_default: False})
        cfg.is_default = True
    
    db.commit(); db.refresh(cfg)
    return to_response(cfg)

@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    cfg = db.query(AIProviderConfig).filter(AIProviderConfig.id==provider_id, AIProviderConfig.company_id==current_user.company_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Fournisseur non trouvé")
    db.delete(cfg); db.commit()
    return {"message": "Fournisseur supprimé"}

@router.post("/providers/test", response_model=AITestResponse)
async def test_provider(payload: AITestRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    start = time.time()
    manager = AIServiceManager(db, current_user.company_id)
    
    # if provider_id provided, load config
    cfg = None
    if payload.provider_id:
        cfg = db.query(AIProviderConfig).filter(AIProviderConfig.id==payload.provider_id, AIProviderConfig.company_id==current_user.company_id).first()
        if not cfg:
            raise HTTPException(status_code=404, detail="Fournisseur non trouvé")
    
    try:
        if payload.provider == "ollama" or (cfg and cfg.provider == "ollama"):
            url = payload.ollama_url or (cfg.ollama_url if cfg else "http://host.docker.internal:11434")
            model = payload.ollama_model or (cfg.ollama_model if cfg else "llama3.2")
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{url.rstrip('/')}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    latency = int((time.time()-start)*1000)
                    # update last test if cfg
                    if cfg:
                        cfg.last_test_at = datetime.now(timezone.utc)
                        cfg.last_test_status = "success"
                        cfg.last_test_message = f"Connexion OK, {len(models)} modèles"
                        db.commit()
                    return {"success": True, "message": f"Ollama accessible, {len(models)} modèles disponibles", "models": models, "latency_ms": latency}
                else:
                    raise HTTPException(status_code=400, detail=f"Ollama erreur {resp.status_code}")
        else:
            # CodeCraftAPI / OpenAI compatible
            base_url = payload.api_base_url or (cfg.api_base_url if cfg else "https://www.codecraftapi.com/v1")
            api_key = payload.api_key or (cfg.api_key_encrypted if cfg else None)
            if not api_key:
                raise HTTPException(status_code=400, detail="Clé API manquante")
            headers = {"Authorization": f"Bearer {api_key}"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["id"] for m in data.get("data", [])] if "data" in data else []
                    latency = int((time.time()-start)*1000)
                    if cfg:
                        cfg.last_test_at = datetime.now(timezone.utc)
                        cfg.last_test_status = "success"
                        cfg.last_test_message = "Connexion OK"
                        db.commit()
                    return {"success": True, "message": "Connexion réussie", "models": models, "latency_ms": latency}
                else:
                    body = resp.text[:500]
                    if cfg:
                        cfg.last_test_at = datetime.now(timezone.utc)
                        cfg.last_test_status = "failed"
                        cfg.last_test_message = body
                        db.commit()
                    return {"success": False, "message": f"Erreur {resp.status_code}: {body}", "models": None, "latency_ms": int((time.time()-start)*1000)}
    except httpx.ConnectError as e:
        if cfg:
            cfg.last_test_at = datetime.now(timezone.utc)
            cfg.last_test_status = "failed"
            cfg.last_test_message = str(e)[:500]
            db.commit()
        return {"success": False, "message": f"Impossible de se connecter: {str(e)} — Vérifiez l'URL (en Docker, utilisez host.docker.internal pour Ollama)", "models": None, "latency_ms": int((time.time()-start)*1000)}
    except Exception as e:
        return {"success": False, "message": str(e), "models": None, "latency_ms": int((time.time()-start)*1000)}

@router.get("/providers/{provider_id}/models")
async def get_models(provider_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cfg = db.query(AIProviderConfig).filter(AIProviderConfig.id==provider_id, AIProviderConfig.company_id==current_user.company_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Fournisseur non trouvé")
    
    if cfg.provider == "ollama":
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{cfg.ollama_url.rstrip('/')}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    return {"models": [m["name"] for m in data.get("models", [])]}
                return {"models": [], "error": resp.text}
        except Exception as e:
            return {"models": [], "error": str(e)}
    else:
        if not cfg.api_key_encrypted:
            raise HTTPException(status_code=400, detail="Clé API manquante")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{cfg.api_base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {cfg.api_key_encrypted}"})
                if resp.status_code == 200:
                    data = resp.json()
                    return {"models": [m["id"] for m in data.get("data", [])]}
                raise HTTPException(status_code=400, detail=resp.text)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

@router.post("/generate", response_model=AIGenerateResponse)
async def generate(payload: AIGenerateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    manager = AIServiceManager(db, current_user.company_id)
    try:
        result = await manager.generate(
            prompt=payload.prompt,
            feature=payload.feature,
            provider_id=payload.provider_id,
            max_tokens=payload.max_tokens,
            temperature=payload.temperature,
            context=payload.context
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/summary/client", response_model=AIGenerateResponse)
async def summarize_client(payload: AISummaryRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = db.query(Client).filter(Client.id==payload.client_id, Client.company_id==current_user.company_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouvé")
    # gather context
    opps = db.query(Opportunity).filter(Opportunity.client_id==client.id).all()
    acts = db.query(Activity).filter(Activity.client_id==client.id).order_by(Activity.created_at.desc()).limit(10).all()
    
    prompt = f"""Tu es un assistant commercial pour Prime CRM. Résume la fiche client suivante de manière concise et professionnelle.

Client: {client.company_name} ({client.type})
Secteur: {client.sector or 'Non renseigné'} | Source: {client.source or 'Non renseignée'}
Contact: {client.first_name or ''} {client.last_name or ''} - {client.email or ''} - {client.phone or ''}
Ville: {client.city or ''} | Notes: {client.notes or 'Aucune'}

Opportunités ({len(opps)}):
"""
    for o in opps[:5]:
        prompt += f"- {o.title}: {o.amount} TND, probabilité {o.probability}%, prochaine action: {o.next_action or 'Aucune'}\n"
    prompt += f"\nDernières activités ({len(acts)}):\n"
    for a in acts[:5]:
        prompt += f"- {a.type}: {a.title} ({a.status})\n"
    prompt += "\nFournis: 1) Résumé global 2) Points d'attention 3) Suggestions de prochaines actions. Distingue les données vérifiées des suggestions."
    
    manager = AIServiceManager(db, current_user.company_id)
    try:
        result = await manager.generate(prompt=prompt, feature="client_summary", context={"client_id": client.id})
        return result
    except Exception as e:
        # fallback if no AI configured: return rule-based summary
        fallback = f"**Résumé {client.company_name}**\nType: {client.type} | Secteur: {client.sector or 'N/A'} | Source: {client.source or 'N/A'}\n{len(opps)} opportunité(s), {len(acts)} activité(s).\n\n"
        if opps:
            total = sum(o.amount or 0 for o in opps)
            fallback += f"Valeur totale des opportunités: {total} TND\n"
        fallback += "\n*Généré sans IA (aucun fournisseur configuré) - Configurez Ollama ou CodeCraftAPI dans Paramètres > IA*"
        return {"content": fallback, "provider": "fallback", "model": "rule-based", "is_verified": False}

@router.post("/extract", response_model=AIGenerateResponse)
async def extract_info(payload: AIExtractRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    prompt = f"""Extrait les informations structurées du texte suivant. Retourne un JSON valide.

Texte:
{payload.text}

Schéma attendu: {payload.schema_hint or 'Extrais nom, entreprise, email, téléphone, besoin, montant estimé'}

Réponds uniquement avec le JSON."""
    manager = AIServiceManager(db, current_user.company_id)
    try:
        result = await manager.generate(prompt=prompt, feature="extraction", context={})
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/draft/email", response_model=AIGenerateResponse)
async def draft_email(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client_id = payload.get("client_id")
    context_text = payload.get("context", "")
    tone = payload.get("tone", "professionnel")
    client = db.query(Client).filter(Client.id==client_id, Client.company_id==current_user.company_id).first() if client_id else None
    prompt = f"""Rédige un brouillon d'email commercial en français, ton {tone}.

Client: {client.company_name if client else 'Prospect'} ({client.email if client and client.email else ''})
Contexte: {context_text}

L'email doit être: professionnel, concis, avec objet et corps. Ne pas inventer de données manquantes, indique [À compléter] si nécessaire."""
    manager = AIServiceManager(db, current_user.company_id)
    try:
        result = await manager.generate(prompt=prompt, feature="email_draft", context=payload)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/health")
def ai_health(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    configs = db.query(AIProviderConfig).filter(AIProviderConfig.company_id==current_user.company_id).all()
    return {
        "providers_count": len(configs),
        "active_providers": len([c for c in configs if c.is_active]),
        "has_default": any(c.is_default for c in configs),
        "providers": [{"provider": c.provider, "is_active": c.is_active, "last_status": c.last_test_status} for c in configs],
        "fallback_available": True,
        "message": "Le CRM fonctionne sans IA. L'IA est facultative et configurable."
    }
