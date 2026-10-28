from pydantic_settings import BaseSettings
from typing import Optional
import os
import json

class Settings(BaseSettings):
    PROJECT_NAME: str = "Prime CRM"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "prime-crm-secret-key-change-in-production-please-use-long-random-string")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALGORITHM: str = "HS256"
    
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./prime_crm.db")
    # Pour PostgreSQL en prod: postgresql://user:password@db:5432/primecrm
    
    # IMPORTANT: gardé en str pour éviter le décodage JSON de pydantic-settings
    # qui plante sur "http://a,http://b" (non-JSON). On expose cors_origins_list pour l'usage.
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,http://localhost:80"

    @property
    def cors_origins_list(self) -> list[str]:
        v = self.CORS_ORIGINS
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(s).strip() for s in parsed if str(s).strip()]
                except:
                    pass
            return [s.strip() for s in v.split(",") if s.strip()]
        return v if isinstance(v, list) else []
    
    # First admin creation
    FIRST_SUPERUSER_EMAIL: str = os.getenv("FIRST_SUPERUSER_EMAIL", "admin@primevisionsolutions.tn")
    FIRST_SUPERUSER_PASSWORD: str = os.getenv("FIRST_SUPERUSER_PASSWORD", "Admin123!")
    FIRST_SUPERUSER_COMPANY: str = os.getenv("FIRST_COMPANY_NAME", "Prime Vision Solutions")
    
    # Uploads
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./uploads")
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB
    
    # Pagination
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
