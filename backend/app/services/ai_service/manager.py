import json
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from ...models.ai_provider import AIProviderConfig
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

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
            # openai_compat includes codecraftapi
            return OpenAICompatProvider(base_url=cfg.api_base_url or "https://www.codecraftapi.com/v1", api_key=cfg.api_key_encrypted, model=cfg.model_id or "gpt-4o-mini", timeout=cfg.timeout_seconds or 30)
    
    async def generate(self, prompt: str, feature: str = None, provider_id: int = None, max_tokens: int = None, temperature: float = None, context: Dict[str, Any] = None) -> Dict[str, Any]:
        cfg = self.get_provider_config(feature=feature, provider_id=provider_id)
        if not cfg:
            raise Exception("Aucun fournisseur IA configuré ou activé. Configurez Ollama (local, gratuit) ou CodeCraftAPI dans Paramètres > Intelligence artificielle. Le CRM reste entièrement fonctionnel sans IA.")
        
        provider = self._instantiate_provider(cfg)
        model = cfg.model_id if cfg.provider != "ollama" else cfg.ollama_model
        temp = temperature if temperature is not None else (cfg.temperature or 0.7)
        tokens = max_tokens or cfg.max_tokens or 1000
        timeout = cfg.timeout_seconds or 30
        
        # Security: limit data transmitted to necessary info only
        # We already construct prompt with minimal needed data; log that external call happens if provider is external
        is_external = cfg.provider != "ollama"
        
        try:
            content = await provider.generate(prompt=prompt, model=model, temperature=temp, max_tokens=tokens, timeout=timeout)
            
            # Ensure response distinguishes verified vs suggestion
            # If prompt didn't already ask, prepend disclaimer if needed?
            
            return {
                "content": content,
                "provider": cfg.provider,
                "model": model,
                "is_verified": False,  # IA outputs are always suggestions to verify
                "tokens_used": None
            }
        except Exception as e:
            # Try fallback to another provider if available
            # Don't expose raw api key errors
            raise Exception(f"Erreur IA ({cfg.provider}/{model}): {str(e)[:400]}. Vérifiez la configuration dans Paramètres > IA. L'échec de l'IA n'affecte pas les fonctions essentielles du CRM.")
