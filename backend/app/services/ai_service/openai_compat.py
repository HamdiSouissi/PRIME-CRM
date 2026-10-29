from typing import List

from .base import AIProviderBase
from .egress import request_provider
from .provider_urls import AIProviderURLError, validate_openai_base_url


class OpenAICompatProvider(AIProviderBase):
    """OpenAI-compatible provider using the single guarded egress path."""

    def __init__(self, base_url: str | None, api_key: str, model: str = "gpt-4o-mini", timeout: int = 30):
        self.base_url = validate_openai_base_url(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def generate(self, prompt: str, model: str = None, temperature: float = 0.7, max_tokens: int = 1000, timeout: int = 30) -> str:
        payload = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": "Tu es un assistant commercial expert pour Prime CRM, édité par Prime Vision Solutions. Réponds en français, de manière professionnelle et concise. Distingue toujours les données vérifiées, les estimations et les suggestions."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response = await request_provider(
            self.base_url, ollama=False, method="POST", endpoint="/chat/completions",
            api_key=self.api_key, json=payload, timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "") or choices[0].get("text", "")
        else:
            content = data.get("response", "") or str(data)
        if not isinstance(content, str) or (self.api_key and self.api_key in content):
            raise AIProviderURLError("Réponse du fournisseur IA invalide ou masquée.")
        return content

    async def list_models(self) -> List[str]:
        response = await request_provider(
            self.base_url, ollama=False, method="GET", endpoint="/models", api_key=self.api_key, timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if "data" in data:
            return [m["id"] for m in data["data"] if isinstance(m, dict) and isinstance(m.get("id"), str) and self.api_key not in m["id"]]
        if "models" in data:
            return [m for m in data["models"] if isinstance(m, str) and self.api_key not in m]
        return []

    async def health_check(self) -> bool:
        try:
            await self.list_models()
            return True
        except Exception:
            try:
                await self.generate("Dis bonjour", max_tokens=5, timeout=10)
                return True
            except Exception:
                return False
