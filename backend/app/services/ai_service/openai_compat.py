import httpx
from typing import List
from .base import AIProviderBase

class OpenAICompatProvider(AIProviderBase):
    """
    Compatible OpenAI / CodeCraftAPI: POST /chat/completions, GET /models
    """
    def __init__(self, base_url: str, api_key: str, model: str = "gpt-4o-mini", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
    
    async def generate(self, prompt: str, model: str = None, temperature: float = 0.7, max_tokens: int = 1000, timeout: int = 30) -> str:
        use_model = model or self.model
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": use_model,
            "messages": [
                {"role": "system", "content": "Tu es un assistant commercial expert pour Prime CRM, édité par Prime Vision Solutions. Réponds en français, de manière professionnelle et concise. Distingue toujours les données vérifiées, les estimations et les suggestions."},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            # OpenAI format
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "") or choices[0].get("text", "")
            return data.get("response", "") or str(data)
    
    async def list_models(self) -> List[str]:
        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            # data: {"data": [{"id": "gpt-4", ...}]}
            if "data" in data:
                return [m["id"] for m in data["data"]]
            if "models" in data:
                return data["models"]
            return []
    
    async def health_check(self) -> bool:
        try:
            await self.list_models()
            return True
        except:
            # try a minimal generation
            try:
                await self.generate("Dis bonjour", max_tokens=5, timeout=10)
                return True
            except:
                return False
