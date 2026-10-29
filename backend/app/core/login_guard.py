"""Pre-validation login limits with a bounded local Redis-protection layer."""

from collections import OrderedDict, deque
import hashlib
import hmac
import math
import secrets
import threading
import time
from typing import Callable

from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .client_ip import ClientIPError, is_trusted_proxy_peer, resolve_client_ip
from ..services.redis_store import IP_LOGIN_WINDOW_SECONDS, LoginRateLimited, RedisStore


LOCAL_LOGIN_ATTEMPTS = 60
LOCAL_LOGIN_WINDOW_SECONDS = 60
LOCAL_BLOCKED_IP_CAPACITY = 4096


class LocalLoginGuard:
    """Bounded, per-process load shedding; Redis remains the shared authority.

    A short global budget limits the rate of Redis calls, even when the caller
    rotates IPs. A negative cache skips Redis for already-blocked IPs. Neither
    mechanism is shared between workers or a substitute for edge protection.
    """

    def __init__(
        self,
        *,
        limit: int = LOCAL_LOGIN_ATTEMPTS,
        window: int = LOCAL_LOGIN_WINDOW_SECONDS,
        capacity: int = LOCAL_BLOCKED_IP_CAPACITY,
        clock: Callable[[], float] = time.monotonic,
    ):
        if limit < 1 or window < 1 or capacity < 1:
            raise ValueError("Invalid local login guard configuration")
        self._limit, self._window, self._capacity, self._clock = limit, window, capacity, clock
        self._lock = threading.Lock()
        self._secret = secrets.token_bytes(32)
        self._events: deque[float] = deque()
        self._blocked: OrderedDict[bytes, float] = OrderedDict()

    def _key(self, client_ip: str) -> bytes:
        return hmac.new(self._secret, client_ip.encode("ascii"), hashlib.sha256).digest()

    def precheck(self, client_ip: str) -> int | None:
        key = self._key(client_ip)
        with self._lock:
            now = self._clock()
            until = self._blocked.get(key)
            if until is not None:
                if until > now:
                    # A cached denial does not touch Redis, so it must not
                    # exhaust the shared worker budget for other clients.
                    self._blocked.move_to_end(key)
                    return max(1, math.ceil(until - now))
                del self._blocked[key]
            while self._events and self._events[0] <= now - self._window:
                self._events.popleft()
            if len(self._events) >= self._limit:
                return max(1, math.ceil(self._events[0] + self._window - now))
            self._events.append(now)
            return None

    def remember_blocked(self, client_ip: str, retry_after: int) -> None:
        key = self._key(client_ip)
        # A damaged Redis TTL cannot pin a local denial forever. If Redis has a
        # longer TTL, it will still reject the next check after this cache ends.
        seconds = min(IP_LOGIN_WINDOW_SECONDS, max(1, retry_after))
        with self._lock:
            self._blocked[key] = self._clock() + seconds
            self._blocked.move_to_end(key)
            while len(self._blocked) > self._capacity:
                self._blocked.popitem(last=False)

    def reset(self) -> None:
        """Clear process-local state; used for isolated tests, not auth resets."""
        with self._lock:
            self._events.clear()
            self._blocked.clear()


def _response(status: int, retry_after: int | None = None) -> JSONResponse:
    headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
    if retry_after is not None:
        headers["Retry-After"] = str(max(1, retry_after))
    detail = (
        "Trop de tentatives. Réessayez plus tard."
        if status == 429
        else "Service de sécurité temporairement indisponible"
    )
    return JSONResponse(status_code=status, content={"detail": detail}, headers=headers)


class TrustedProxyHTTPSMiddleware:
    """Preserve HTTPS redirects when an explicitly trusted proxy terminates TLS.

    The operator must enforce HTTPS at that public ingress. No forwarded-proto
    header is trusted, and an untrusted peer cannot change the ASGI scheme.
    """

    def __init__(self, app, *, config):
        self.app, self.config = app, config

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") in {"http", "websocket"}
            and self.config.APP_ENV == "production"
            and is_trusted_proxy_peer(scope, self.config)
        ):
            scope = dict(scope)
            scope["scheme"] = "wss" if scope["type"] == "websocket" else "https"
        await self.app(scope, receive, send)


class LoginIPMiddleware:
    """Count both login routes before parsing or validating their bodies."""

    def __init__(self, app, *, config, store_provider: Callable[[], RedisStore | None], guard: LocalLoginGuard):
        self.app = app
        self.config = config
        self.store_provider = store_provider
        self.guard = guard

    async def __call__(self, scope, receive, send):
        prefix = self.config.API_V1_STR.rstrip("/")
        path = scope.get("path", "").rstrip("/")
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or path not in {f"{prefix}/auth/login", f"{prefix}/auth/login-json"}
        ):
            await self.app(scope, receive, send)
            return

        try:
            store = self.store_provider()
        except (RedisError, ValueError):
            await _response(503)(scope, receive, send)
            return
        if store is None:
            if self.config.APP_ENV == "production":
                await _response(503)(scope, receive, send)
            else:
                # Consistent with the existing explicit development/test mode:
                # all Redis-based login limits are disabled without Redis.
                await self.app(scope, receive, send)
            return

        try:
            client_ip = resolve_client_ip(scope, self.config)
        except ClientIPError:
            await _response(503)(scope, receive, send)
            return

        local_retry = self.guard.precheck(client_ip)
        if local_retry is not None:
            await _response(429, local_retry)(scope, receive, send)
            return
        try:
            # redis-py is synchronous; never block the ASGI event loop on I/O.
            await run_in_threadpool(store.record_login_ip, client_ip)
        except LoginRateLimited as exc:
            retry = min(IP_LOGIN_WINDOW_SECONDS, exc.retry_after)
            self.guard.remember_blocked(client_ip, retry)
            await _response(429, retry)(scope, receive, send)
            return
        except (RedisError, ValueError, UnicodeError):
            await _response(503)(scope, receive, send)
            return

        await self.app(scope, receive, send)
