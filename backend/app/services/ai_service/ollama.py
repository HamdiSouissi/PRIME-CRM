import httpx
from typing import List
from .base import AIProviderBase

class OllamaProvider(AIProviderBase):
    def __init__(self, base_url: str, model: str = "llama3.2", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
    
    async def generate(self, prompt: str, model: str = None, temperature: float = 0.7, max_tokens: int = 1000, timeout: int = 30) -> str:
        use_model = model or self.model
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": use_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")
    
    async def list_models(self) -> List[str]:
        url = f"{self.base_url}/api/tags"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
    
    async def health_check(self) -> bool:
        try:
            models = await self.list_models()
            return True
        except:
            return False

    async def chat(self, prompt: str, model: str = None, temperature: float = 0.7, max_tokens: int = 1000, timeout: int = 30) -> str:
        # Try chat endpoint for better instruction following
        use_model = model or self.model
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": use_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens}
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("message", {}).get("content", "") or data.get("response", "")
        except:
            # fallback to generate
            return await self.generate(prompt, model, temperature, max_tokens, timeout)
