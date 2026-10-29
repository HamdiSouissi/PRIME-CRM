import json
from typing import Literal
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Prime CRM"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # Production is the fail-closed default; development must be explicit.
    APP_ENV: Literal["production", "development", "test"] = "production"
    SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    ALGORITHM: str = "HS256"
    DATABASE_URL: str = "sqlite:///./prime_crm.db"
    # Production requires an authenticated TLS Redis connection.
    REDIS_URL: str = ""

    # IP remains the default. Global is an explicit alternative when a safe
    # client IP cannot be established; it shares one limit among all visitors.
    LOGIN_LIMIT_SCOPE: Literal["ip", "global"] = "ip"
    CLIENT_IP_MODE: Literal["", "direct", "trusted_proxy"] = ""
    CLIENT_IP_PROXY_HEADER: Literal["", "cf-connecting-ip", "x-real-ip"] = ""
    CLIENT_IP_TRUSTED_PROXIES: str = ""
    # Used only with the global limiter to generate safe HTTPS redirects. The
    # operator must enforce HTTPS at every public ingress separately.
    PUBLIC_API_ORIGIN: str = ""

    # An empty list allows no cross-origin browser requests.
    CORS_ORIGINS: str = ""
    ALLOW_PUBLIC_REGISTRATION: bool = False

    # AI egress is disabled by default. Origins are explicit HTTPS origins,
    # never URLs containing credentials or paths.
    AI_ALLOWED_ORIGINS: str = ""
    AI_ALLOW_LOCAL_OLLAMA: bool = False

    # Only used by the explicit first-administrator bootstrap command.
    FIRST_SUPERUSER_EMAIL: str = ""
    FIRST_SUPERUSER_PASSWORD: str = ""
    FIRST_COMPANY_NAME: str = "Prime Vision Solutions"

    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        # An explicitly empty environment value must override any older .env
        # value (notably, an empty AI allowlist must disable outbound AI).
        env_ignore_empty=False,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        value = self.CORS_ORIGINS.strip()
        if not value:
            return []
        if value.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("CORS_ORIGINS must be a list or comma-separated origins") from exc
            if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
                raise ValueError("CORS_ORIGINS must contain only origin strings")
            return [item.strip() for item in parsed if item.strip()]
        return [item.strip() for item in value.split(",") if item.strip()]

    def validate_web_ip_settings(self) -> None:
        """Validate web-only login and redirect settings without network access.

        Offline bootstrap and Alembic do not receive HTTP requests and do not
        require the deployment's ingress configuration.
        """
        from .core.client_ip import effective_ip_mode
        from .core.public_origin import public_https_origin

        if self.LOGIN_LIMIT_SCOPE == "global":
            if self.CLIENT_IP_MODE or self.CLIENT_IP_PROXY_HEADER or self.CLIENT_IP_TRUSTED_PROXIES:
                raise ValueError("CLIENT_IP settings must be empty with the global login limit")
            if self.APP_ENV == "production" or self.PUBLIC_API_ORIGIN:
                public_https_origin(self.PUBLIC_API_ORIGIN)
        else:
            if self.PUBLIC_API_ORIGIN:
                raise ValueError("PUBLIC_API_ORIGIN is only used with the global login limit")
            effective_ip_mode(self)

    def validate_runtime(self) -> None:
        """Validate the web app/bootstrap configuration without printing values.

        Alembic may import these settings with only DATABASE_URL configured;
        runtime validation is therefore called by the app and bootstrap, not
        while the settings module is imported by the migration environment.
        """
        known_unsafe_keys = {
            "prime-crm-secret-key-change-in-production-please-use-long-random-string",
            "please_generate_a_long_random_secret_key_here_min_32_chars",
        }
        if (
            len(self.SECRET_KEY) < 32
            or len(set(self.SECRET_KEY)) < 8
            or self.SECRET_KEY != self.SECRET_KEY.strip()
            or self.SECRET_KEY in known_unsafe_keys
        ):
            raise ValueError("SECRET_KEY must be a unique, randomly generated value of at least 32 characters")
        if self.ALGORITHM != "HS256":
            raise ValueError("Only the configured HS256 token algorithm is supported")

        if self.APP_ENV == "production":
            from sqlalchemy.engine import make_url

            try:
                database_url = make_url(self.DATABASE_URL)
                valid_database = (
                    database_url.drivername in {"postgresql", "postgresql+psycopg2"}
                    and bool(database_url.host)
                    and bool(database_url.database)
                )
            except Exception:
                valid_database = False
            if not valid_database:
                raise ValueError("Production requires a valid PostgreSQL DATABASE_URL with host and database") from None
            if self.ALLOW_PUBLIC_REGISTRATION:
                raise ValueError("Public registration is disabled in production")

        if self.REDIS_URL:
            try:
                redis_url = urlsplit(self.REDIS_URL)
                port = redis_url.port  # validates malformed or out-of-range ports
                valid_redis = (
                    redis_url.scheme in {"redis", "rediss"}
                    and bool(redis_url.hostname)
                    and (port is None or 0 < port <= 65535)
                    and redis_url.path in {"", "/0"}
                    and not redis_url.query
                    and not redis_url.fragment
                    and not any(char.isspace() for char in self.REDIS_URL)
                )
                if self.APP_ENV == "production":
                    valid_redis = valid_redis and redis_url.scheme == "rediss" and bool(redis_url.password)
            except ValueError:
                valid_redis = False
            if not valid_redis:
                raise ValueError("REDIS_URL must be a valid Redis URL (authenticated TLS in production)") from None
        elif self.APP_ENV == "production":
            raise ValueError("REDIS_URL is required in production")

        # Import here so Alembic can still read DATABASE_URL without requiring
        # a complete runtime configuration or making any network request.
        from .services.ai_service.provider_urls import AIProviderURLError, parse_allowed_origins
        try:
            parse_allowed_origins(self.AI_ALLOWED_ORIGINS)
        except AIProviderURLError:
            raise ValueError("AI_ALLOWED_ORIGINS must contain exact HTTPS origins without credentials or paths") from None
        if self.AI_ALLOW_LOCAL_OLLAMA and self.APP_ENV != "development":
            raise ValueError("AI_ALLOW_LOCAL_OLLAMA is permitted only in development")

        for origin in self.cors_origins_list:
            try:
                parsed = urlsplit(origin)
                # Accessing port also validates malformed ports.
                parsed.port
                valid = (
                    parsed.scheme in {"http", "https"}
                    and bool(parsed.hostname)
                    and parsed.username is None
                    and parsed.password is None
                    and not parsed.path
                    and not parsed.query
                    and not parsed.fragment
                    and "*" not in origin
                    and not any(char.isspace() for char in origin)
                )
            except ValueError:
                valid = False
            if not valid or (self.APP_ENV == "production" and parsed.scheme != "https"):
                raise ValueError("CORS_ORIGINS must contain explicit, valid origins (HTTPS in production)")


settings = Settings()
