"""Small Redis cache and shared login counter; no CRM secrets in Redis values."""

import base64
import hashlib
import hmac
import json
import re
import secrets
import ssl
import unicodedata
from functools import lru_cache
from urllib.parse import urlsplit

import certifi
import redis
from cryptography.fernet import Fernet, InvalidToken
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from ..config import settings
from ..core.client_ip import canonical_client_ip


CACHE_SECONDS = 30
LOGIN_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 15 * 60
IP_LOGIN_ATTEMPTS = 30
IP_LOGIN_WINDOW_SECONDS = 15 * 60
GLOBAL_LOGIN_ATTEMPTS = 30
GLOBAL_LOGIN_WINDOW_SECONDS = 15 * 60
PASSWORD_CHANGE_ATTEMPTS = 5
PASSWORD_CHANGE_WINDOW_SECONDS = 15 * 60

# One key and a server-side atomic operation shared by all API workers.
# A missing TTL is repaired rather than leaving an account blocked forever.
_LOGIN_LUA = """
local count = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
    ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""


class CertifiTLSConnection(redis.connection.Connection):
    """A verified Redis TLS connection using only certifi's public CA bundle.

    redis-py 5.2.1's ssl_ca_certs adds certificates to the system context; it
    does not replace that context. This explicit context avoids also selecting
    an expired CA from the Windows system store while still requiring a valid
    certificate chain and a matching hostname.
    """

    def _connect(self):
        ca_bundle = certifi.where()
        if not ca_bundle:
            # An empty cafile would make create_default_context load OS roots.
            raise ssl.SSLError("Redis CA bundle is unavailable")
        context = ssl.create_default_context(cafile=ca_bundle)
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        # Do not expose Redis TLS session keys through SSLKEYLOGFILE.
        if hasattr(context, "keylog_filename"):
            context.keylog_filename = None
        sock = super()._connect()
        try:
            return context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class LoginRateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = max(1, retry_after)
        super().__init__("Trop de tentatives de connexion")


class RedisStore:
    def __init__(self, client: redis.Redis, secret_key: str, prefix: str = "primecrm:v1"):
        if not re.fullmatch(r"[a-zA-Z0-9:_-]{1,120}", prefix):
            raise ValueError("Invalid Redis namespace")
        self.client = client
        self.prefix = prefix
        secret = secret_key.encode("utf-8")
        self._index_key = hmac.new(secret, b"primecrm:redis:index:v1", hashlib.sha256).digest()
        cipher_key = hmac.new(secret, b"primecrm:redis:cache-fernet:v1", hashlib.sha256).digest()
        self._cipher = Fernet(base64.urlsafe_b64encode(cipher_key))

    def _digest(self, purpose: str, value: str) -> str:
        data = f"{purpose}:{value}".encode("utf-8")
        return hmac.new(self._index_key, data, hashlib.sha256).hexdigest()

    def _stage_key(self, company_id: int) -> str:
        return f"{self.prefix}:stages:{self._digest('company', str(company_id))}"

    def _login_key(self, identifier: str) -> str:
        normalized = unicodedata.normalize("NFKC", identifier).strip().casefold()
        return f"{self.prefix}:login:{self._digest('login', normalized)}"

    def _password_change_key(self, identifier: str) -> str:
        normalized = unicodedata.normalize("NFKC", identifier).strip().casefold()
        return f"{self.prefix}:password-change:{self._digest('password-change', normalized)}"

    def _login_ip_key(self, client_ip: str) -> str:
        # A different purpose prevents correlating these keys with login emails.
        canonical = canonical_client_ip(client_ip)
        return f"{self.prefix}:login-ip:{self._digest('login-ip', canonical)}"

    def _login_global_key(self) -> str:
        # One deployment-wide bucket, independent of user-controlled addresses.
        return f"{self.prefix}:login-global:{self._digest('login-global', 'all')}"

    def check_writable(self) -> None:
        # Also checks authentication and write quota, not just an unbilled PING.
        key = f"{self.prefix}:probe:{secrets.token_hex(16)}"
        if not self.client.set(key, "1", ex=5, nx=True):
            raise RedisError("Redis probe failed")

    def _record_limited_attempt(self, key: str, window: int, limit: int) -> None:
        # All attempts count, successful or not, to keep the operation atomic.
        result = self.client.eval(_LOGIN_LUA, 1, key, window)
        try:
            if not isinstance(result, (list, tuple)) or len(result) != 2:
                raise ValueError("Invalid response shape")
            count, ttl = int(result[0]), int(result[1])
        except (TypeError, ValueError, IndexError):
            raise RedisError("Invalid Redis limiter response") from None
        if count < 1:
            raise RedisError("Invalid Redis limiter response")
        if count > limit:
            raise LoginRateLimited(ttl)

    def record_login(self, identifier: str) -> None:
        self._record_limited_attempt(self._login_key(identifier), LOGIN_WINDOW_SECONDS, LOGIN_ATTEMPTS)

    def record_login_ip(self, client_ip: str) -> None:
        self._record_limited_attempt(self._login_ip_key(client_ip), IP_LOGIN_WINDOW_SECONDS, IP_LOGIN_ATTEMPTS)

    def record_global_login(self) -> None:
        self._record_limited_attempt(self._login_global_key(), GLOBAL_LOGIN_WINDOW_SECONDS, GLOBAL_LOGIN_ATTEMPTS)

    def record_password_change(self, identifier: str) -> None:
        self._record_limited_attempt(
            self._password_change_key(identifier), PASSWORD_CHANGE_WINDOW_SECONDS, PASSWORD_CHANGE_ATTEMPTS
        )

    def get_stage_outcomes(self, company_id: int) -> tuple[list[int], list[int]] | None:
        try:
            encrypted = self.client.get(self._stage_key(company_id))
            if encrypted is None:
                return None
            # Authenticate the tenant and enforce an age bound even if someone
            # incorrectly removes the Redis expiration from a cached token.
            payload = json.loads(self._cipher.decrypt(encrypted.encode("ascii"), ttl=CACHE_SECONDS))
            won, lost = payload["won"], payload["lost"]
            if payload["company_id"] != company_id or not isinstance(won, list) or not isinstance(lost, list):
                return None
            if len(won) + len(lost) > 10_000 or any(type(x) is not int or x < 1 for x in won + lost):
                return None
            return won, lost
        except (RedisError, InvalidToken, KeyError, ValueError, TypeError, UnicodeError):
            return None

    def set_stage_outcomes(self, company_id: int, won: list[int], lost: list[int]) -> None:
        try:
            payload = json.dumps({"company_id": company_id, "won": won, "lost": lost}, separators=(",", ":"))
            encrypted = self._cipher.encrypt(payload.encode("utf-8")).decode("ascii")
            self.client.set(self._stage_key(company_id), encrypted, ex=CACHE_SECONDS)
        except RedisError:
            # PostgreSQL remains authoritative for this non-security cache.
            pass

    def invalidate_stages(self, company_id: int) -> None:
        try:
            self.client.delete(self._stage_key(company_id))
        except RedisError:
            # A missed invalidation may leave metrics stale until the short TTL.
            pass

    def close(self) -> None:
        self.client.close()


def create_redis_store(url: str, secret_key: str, prefix: str = "primecrm:v1") -> RedisStore:
    parsed = urlsplit(url)
    if parsed.scheme not in {"redis", "rediss"} or parsed.query or parsed.fragment:
        raise ValueError("Invalid Redis URL")
    options = {
        "decode_responses": True,
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
        "max_connections": 32,
        "retry": Retry(NoBackoff(), 0),
        "retry_on_timeout": False,
        "health_check_interval": 0,
    }
    if parsed.scheme == "rediss":
        # ConnectionPool.from_url otherwise selects redis-py's SSLConnection.
        options["connection_class"] = CertifiTLSConnection
    return RedisStore(redis.Redis.from_url(url, **options), secret_key, prefix)


@lru_cache(maxsize=1)
def get_redis_store() -> RedisStore | None:
    if not settings.REDIS_URL:
        return None
    return create_redis_store(settings.REDIS_URL, settings.SECRET_KEY)
