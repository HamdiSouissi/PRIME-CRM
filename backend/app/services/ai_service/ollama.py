from typing import List

from .base import AIProviderBase
from .egress import request_provider
from .provider_urls import validate_ollama_base_url


class OllamaProvider(AIProviderBase):
    def __init__(self, base_url: str | None, model: str = "llama3.2", timeout: int = 30):
        self.base_url = validate_ollama_base_url(base_url)
        self.model = model
        self.timeout = timeout

    async def generate(self, prompt: str, model: str = None, temperature: float = 0.7, max_tokens: int = 1000, timeout: int = 30) -> str:
        payload = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        response = await request_provider(
            self.base_url, ollama=True, method="POST", endpoint="/api/generate", json=payload, timeout=timeout,
        )
        response.raise_for_status()
        return response.json().get("response", "")

    async def list_models(self) -> List[str]:
        response = await request_provider(self.base_url, ollama=True, method="GET", endpoint="/api/tags", timeout=10)
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]

    async def health_check(self) -> bool:
        try:
            await self.list_models()
            return True
        except Exception:
            return False

    async def chat(self, prompt: str, model: str = None, temperature: float = 0.7, max_tokens: int = 1000, timeout: int = 30) -> str:
        payload = {
            "model": model or self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            response = await request_provider(
                self.base_url, ollama=True, method="POST", endpoint="/api/chat", json=payload, timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "") or data.get("response", "")
        except Exception:
            # The fallback uses exactly the same destination policy.
            return await self.generate(prompt, model, temperature, max_tokens, timeout)
