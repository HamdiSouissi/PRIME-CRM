from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

class AIProviderBase(ABC):
    @abstractmethod
    async def generate(self, prompt: str, model: str, temperature: float = 0.7, max_tokens: int = 1000, timeout: int = 30) -> str:
        pass
    
    @abstractmethod
    async def list_models(self) -> List[str]:
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        pass
