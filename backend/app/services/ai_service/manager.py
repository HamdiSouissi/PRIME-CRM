import json
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from ...models.ai_provider import AIProviderConfig
from .credentials import AICredentialError, decrypt_credential
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider
from .provider_urls import AIProviderURLError


class AIServiceError(Exception):
    """A sanitized AI failure suitable for displaying to the user."""


class AIServiceManager:
    """
    Abstraction IA: permet de changer de fournisseur sans modifier le cœur métier.
    Supporte Ollama (local) prioritaire et CodeCraftAPI (OpenAI-compatible).
    """
    def __init__(self, db: Session, company_id: int):
        self.db = db
        self.company_id = company_id
    
    def get_provider_config(self, feature: str = None, provider_id: int = None) -> Optional[AIProviderConfig]:
        if provider_id:
            return self.db.query(AIProviderConfig).filter(AIProviderConfig.id==provider_id, AIProviderConfig.company_id==self.company_id).first()
        
        # check feature mapping
        # first try default, then any active, then ollama fallback
        # Look for provider that has this feature mapped
        all_configs = self.db.query(AIProviderConfig).filter(AIProviderConfig.company_id==self.company_id, AIProviderConfig.is_active==True).all()
        if not all_configs:
            return None
        
        # feature mapping logic
        if feature:
            for cfg in all_configs:
                if cfg.feature_mapping:
                    try:
                        mapping = json.loads(cfg.feature_mapping)
                        if feature in mapping:
                            wanted = mapping[feature]
                            # find provider matching wanted
                            for c in all_configs:
                                if c.provider == wanted or c.name == wanted:
                                    return c
                    except:
                        pass
        
        # default provider
        default = next((c for c in all_configs if c.is_default), None)
        if default:
            return default
        
        # prefer ollama if available (gratuit)
        ollama = next((c for c in all_configs if c.provider == "ollama"), None)
        if ollama:
            return ollama
        
        # otherwise first active
        return all_configs[0]
    
    def _instantiate_provider(self, cfg: AIProviderConfig):
        if cfg.provider == "ollama":
            return OllamaProvider(base_url=cfg.ollama_url or "http://host.docker.internal:11434", model=cfg.ollama_model or "llama3.2", timeout=cfg.timeout_seconds or 30)
        else:
            # openai_compat includes codecraftapi. Only the bound, authenticated
            # credential reaches the provider; legacy plaintext is rejected.
            api_key = decrypt_credential(cfg.api_key_encrypted, cfg.company_id, cfg.id)
            if not api_key:
                raise AIServiceError("Clé API IA manquante : vérifiez la configuration.")
            return OpenAICompatProvider(base_url=cfg.api_base_url, api_key=api_key, model=cfg.model_id or "gpt-4o-mini", timeout=cfg.timeout_seconds or 30)
    
    async def generate(self, prompt: str, feature: str = None, provider_id: int = None, max_tokens: int = None, temperature: float = None, context: Dict[str, Any] = None) -> Dict[str, Any]:
        cfg = self.get_provider_config(feature=feature, provider_id=provider_id)
        if not cfg:
            raise AIServiceError("Aucun fournisseur IA configuré ou activé. Le CRM reste fonctionnel sans IA.")

        model = cfg.model_id if cfg.provider != "ollama" else cfg.ollama_model
        temp = temperature if temperature is not None else (cfg.temperature or 0.7)
        tokens = max_tokens or cfg.max_tokens or 1000
        timeout = cfg.timeout_seconds or 30

        try:
            provider = self._instantiate_provider(cfg)
            content = await provider.generate(prompt=prompt, model=model, temperature=temp, max_tokens=tokens, timeout=timeout)
            return {
                "content": content,
                "provider": cfg.provider,
                "model": model,
                "is_verified": False,  # IA outputs are always suggestions to verify
                "tokens_used": None
            }
        except AIServiceError:
            raise
        except (AICredentialError, AIProviderURLError) as exc:
            raise AIServiceError(str(exc)) from None
        except Exception:
            # Third-party responses and exceptions can contain credentials.
            raise AIServiceError("Erreur du fournisseur IA. Vérifiez sa configuration ; le CRM reste fonctionnel sans IA.") from None
