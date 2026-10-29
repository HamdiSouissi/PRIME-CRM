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
from ..services.ai_service.credentials import (
    AICredentialError, CREDENTIAL_ERROR, credential_needs_reset, decrypt_credential, encrypt_credential,
)
from ..services.ai_service.egress import request_provider
from ..services.ai_service.manager import AIServiceError, AIServiceManager
from ..services.ai_service.provider_urls import (
    AIProviderURLError, DEFAULT_OLLAMA_BASE_URL, DEFAULT_OPENAI_BASE_URL, response_url,
    validate_ollama_base_url, validate_openai_base_url,
)

router = APIRouter(prefix="/ai", tags=["ai"])


def to_response(cfg: AIProviderConfig):
    # Old versions persisted provider error bodies verbatim. Never return those
    # legacy messages or fragments of a credential, even to an administrator.
    last_message = None
    if cfg.last_test_status == "success":
        last_message = "Connexion réussie."
    elif cfg.last_test_status == "failed":
        last_message = "Test échoué : vérifiez la configuration."
    return {
        "id": cfg.id,
        "company_id": cfg.company_id,
        "provider": cfg.provider,
        "name": cfg.name,
        "is_active": cfg.is_active,
        "is_default": cfg.is_default,
        "ollama_url": response_url(cfg.ollama_url),
        "ollama_model": cfg.ollama_model,
        "api_base_url": response_url(cfg.api_base_url),
        "api_key_masked": "***" if cfg.api_key_encrypted else None,
        "api_key_needs_reset": credential_needs_reset(cfg.api_key_encrypted, cfg.company_id, cfg.id),
        "model_id": cfg.model_id,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "timeout_seconds": cfg.timeout_seconds,
        "feature_mapping": json.loads(cfg.feature_mapping) if cfg.feature_mapping else None,
        "last_test_at": cfg.last_test_at,
        "last_test_status": cfg.last_test_status,
        "last_test_message": last_message,
        "created_at": cfg.created_at
    }

@router.get("/providers", response_model=List[AIProviderResponse])
def list_providers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    configs = db.query(AIProviderConfig).filter(AIProviderConfig.company_id == current_user.company_id).all()
    return [to_response(c) for c in configs]

@router.post("/providers", response_model=AIProviderResponse)
def create_provider(payload: AIProviderCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    if payload.provider not in {"ollama", "openai_compat", "codecraftapi"}:
        raise HTTPException(status_code=400, detail="Type de fournisseur IA invalide.")
    try:
        if payload.provider == "ollama":
            validate_ollama_base_url(payload.ollama_url)
        else:
            validate_openai_base_url(payload.api_base_url)
    except AIProviderURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

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
        model_id=payload.model_id,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        timeout_seconds=payload.timeout_seconds,
        feature_mapping=json.dumps(payload.feature_mapping) if payload.feature_mapping else None
    )
    db.add(cfg)
    # Bind the ciphertext to this provider's ID, within the same transaction.
    # The unencrypted input is never assigned to a database column.
    db.flush()
    try:
        cfg.api_key_encrypted = encrypt_credential(payload.api_key, cfg.company_id, cfg.id)
    except AICredentialError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    db.commit()
    db.refresh(cfg)
    return to_response(cfg)

@router.put("/providers/{provider_id}", response_model=AIProviderResponse)
def update_provider(provider_id: int, payload: AIProviderUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    cfg = db.query(AIProviderConfig).filter(AIProviderConfig.id==provider_id, AIProviderConfig.company_id==current_user.company_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Fournisseur non trouvé")
    
    data = payload.model_dump(exclude_unset=True)
    url_changed = False
    try:
        if cfg.provider == "ollama" and ("ollama_url" in data or data.get("is_active") is True):
            old_url = (cfg.ollama_url or DEFAULT_OLLAMA_BASE_URL).rstrip("/")
            new_url = validate_ollama_base_url(data.get("ollama_url", cfg.ollama_url))
            url_changed = old_url != new_url
        elif cfg.provider != "ollama" and ("api_base_url" in data or data.get("is_active") is True):
            # Unsafe legacy providers can still be disabled or repaired.
            old_url = (cfg.api_base_url or DEFAULT_OPENAI_BASE_URL).rstrip("/")
            new_url = validate_openai_base_url(data.get("api_base_url", cfg.api_base_url))
            url_changed = old_url != new_url
            if url_changed and cfg.api_key_encrypted and "api_key" not in data:
                raise HTTPException(
                    status_code=400,
                    detail="Pour changer l'URL, remplacez ou supprimez aussi la clé API enregistrée.",
                )
    except AIProviderURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if "api_key" in data:
        try:
            cfg.api_key_encrypted = encrypt_credential(data.pop("api_key"), cfg.company_id, cfg.id)
        except AICredentialError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        # Previous versions may have persisted sensitive error bodies here.
        cfg.last_test_at = cfg.last_test_status = cfg.last_test_message = None
    elif url_changed:
        cfg.last_test_at = cfg.last_test_status = cfg.last_test_message = None
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

def _record_test(db: Session, cfg: AIProviderConfig | None, status: str, message: str) -> None:
    if cfg:
        cfg.last_test_at = datetime.now(timezone.utc)
        cfg.last_test_status = status
        cfg.last_test_message = message
        db.commit()


def _safe_models(items, field: str, secret: str | None = None) -> list[str]:
    """Do not echo a credential if a provider mistakenly includes it in an ID."""
    if not isinstance(items, list):
        return []
    names = []
    for item in items[:1000]:
        name = item.get(field) if isinstance(item, dict) else None
        if isinstance(name, str) and len(name) <= 256 and (not secret or secret not in name):
            names.append(name)
    return names


@router.post("/providers/test", response_model=AITestResponse)
async def test_provider(payload: AITestRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    start = time.time()
    cfg = None
    if payload.provider_id is not None:
        cfg = db.query(AIProviderConfig).filter(AIProviderConfig.id == payload.provider_id, AIProviderConfig.company_id == current_user.company_id).first()
        if not cfg:
            raise HTTPException(status_code=404, detail="Fournisseur non trouvé")
        # A saved credential may only be sent to its saved provider URL. The
        # previous endpoint allowed any user to override this URL in a request.
        if payload.provider is not None and payload.provider != cfg.provider:
            raise HTTPException(status_code=400, detail="Utilisez le fournisseur enregistré pour ce test.")
        saved_api_url = (cfg.api_base_url or DEFAULT_OPENAI_BASE_URL).rstrip("/")
        saved_ollama_url = (cfg.ollama_url or DEFAULT_OLLAMA_BASE_URL).rstrip("/")
        if payload.api_base_url is not None and payload.api_base_url.rstrip("/") != saved_api_url:
            raise HTTPException(status_code=400, detail="Utilisez l'URL enregistrée pour ce test.")
        if payload.ollama_url is not None and payload.ollama_url.rstrip("/") != saved_ollama_url:
            raise HTTPException(status_code=400, detail="Utilisez l'URL enregistrée pour ce test.")

    try:
        is_ollama = cfg.provider == "ollama" if cfg else payload.provider == "ollama"
        if is_ollama:
            url = cfg.ollama_url if cfg else payload.ollama_url
            resp = await request_provider(url, ollama=True, method="GET", endpoint="/api/tags", timeout=10)
            if resp.status_code == 200:
                models = _safe_models(resp.json().get("models", []), "name")
                _record_test(db, cfg, "success", "Connexion réussie.")
                return {"success": True, "message": f"Ollama accessible, {len(models)} modèles disponibles", "models": models, "latency_ms": int((time.time()-start)*1000)}
        else:
            base_url = validate_openai_base_url(cfg.api_base_url if cfg else payload.api_base_url)
            api_key = payload.api_key or (decrypt_credential(cfg.api_key_encrypted, cfg.company_id, cfg.id) if cfg else None)
            if not api_key:
                raise HTTPException(status_code=400, detail="Clé API manquante")
            resp = await request_provider(base_url, ollama=False, method="GET", endpoint="/models", api_key=api_key, timeout=10)
            if resp.status_code == 200:
                models = _safe_models(resp.json().get("data", []), "id", api_key)
                _record_test(db, cfg, "success", "Connexion réussie.")
                return {"success": True, "message": "Connexion réussie", "models": models, "latency_ms": int((time.time()-start)*1000)}

        # Provider responses and exceptions may echo credentials. Persist and
        # return only fixed text and an HTTP status code, never response bodies.
        message = f"Le fournisseur IA a répondu avec le code HTTP {resp.status_code}."
        _record_test(db, cfg, "failed", message)
        return {"success": False, "message": message, "models": None, "latency_ms": int((time.time()-start)*1000)}
    except HTTPException:
        raise
    except AICredentialError:
        _record_test(db, cfg, "failed", CREDENTIAL_ERROR)
        return {"success": False, "message": CREDENTIAL_ERROR, "models": None, "latency_ms": int((time.time()-start)*1000)}
    except AIProviderURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except httpx.RequestError:
        message = "Impossible de joindre le fournisseur IA. Vérifiez sa configuration."
        _record_test(db, cfg, "failed", message)
        return {"success": False, "message": message, "models": None, "latency_ms": int((time.time()-start)*1000)}
    except Exception:
        message = "Le test du fournisseur IA a échoué. Vérifiez sa configuration."
        _record_test(db, cfg, "failed", message)
        return {"success": False, "message": message, "models": None, "latency_ms": int((time.time()-start)*1000)}


@router.get("/providers/{provider_id}/models")
async def get_models(provider_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    cfg = db.query(AIProviderConfig).filter(AIProviderConfig.id == provider_id, AIProviderConfig.company_id == current_user.company_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Fournisseur non trouvé")

    try:
        if cfg.provider == "ollama":
            resp = await request_provider(cfg.ollama_url, ollama=True, method="GET", endpoint="/api/tags", timeout=10)
            if resp.status_code == 200:
                return {"models": _safe_models(resp.json().get("models", []), "name")}
        else:
            base_url = validate_openai_base_url(cfg.api_base_url)
            api_key = decrypt_credential(cfg.api_key_encrypted, cfg.company_id, cfg.id)
            if not api_key:
                raise HTTPException(status_code=400, detail="Clé API manquante")
            resp = await request_provider(base_url, ollama=False, method="GET", endpoint="/models", api_key=api_key, timeout=10)
            if resp.status_code == 200:
                return {"models": _safe_models(resp.json().get("data", []), "id", api_key)}
        raise HTTPException(status_code=400, detail=f"Le fournisseur IA a répondu avec le code HTTP {resp.status_code}.")
    except HTTPException:
        raise
    except AICredentialError:
        raise HTTPException(status_code=400, detail=CREDENTIAL_ERROR) from None
    except AIProviderURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=400, detail="Impossible de récupérer les modèles IA. Vérifiez la configuration.") from None


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
    except AIServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=500, detail="Erreur interne du service IA.") from None

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
        fallback += "\n*Généré sans IA (fournisseur indisponible ou non configuré) - Configurez Ollama ou CodeCraftAPI dans Paramètres > IA*"
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
    except AIServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=500, detail="Erreur interne du service IA.") from None

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
    except AIServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=500, detail="Erreur interne du service IA.") from None

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
