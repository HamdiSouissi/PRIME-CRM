from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import secrets
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from ..config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_NONCE_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_JTI_PATTERN = re.compile(r"[A-Za-z0-9_-]{32}\Z")


def is_acceptable_new_password(password: str) -> bool:
    """Reject weak/ambiguous inputs and bcrypt's silent 72-byte truncation."""
    try:
        return len(password) >= 16 and len(password.encode("utf-8")) <= 72 and password == password.strip()
    except UnicodeEncodeError:
        return False


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # bcrypt silently truncates longer passwords. Never authenticate such an
    # ambiguous input, including when checking an existing password.
    try:
        if len(plain_password) > 72 or len(plain_password.encode("utf-8")) > 72:
            return False
        return pwd_context.verify(plain_password, hashed_password)
    except (TypeError, ValueError, UnicodeEncodeError):
        return False


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def new_session_nonce() -> str:
    """Generate a new per-user revocation epoch, not a bearer credential."""
    return secrets.token_urlsafe(32)


def is_valid_session_nonce(value: object) -> bool:
    return isinstance(value, str) and _NONCE_PATTERN.fullmatch(value) is not None


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: int
    session_nonce: str


def create_access_token(subject: int, *, session_nonce: str, expires_delta: Optional[timedelta] = None) -> str:
    if not is_valid_session_nonce(session_nonce):
        raise ValueError("Invalid session nonce")
    now = datetime.now(timezone.utc)
    lifetime = expires_delta if expires_delta is not None else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(subject),
        "sid": session_nonce,
        "jti": secrets.token_urlsafe(24),
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[AccessTokenClaims]:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require_sub": True, "require_exp": True, "require_iat": True, "require_jti": True},
        )
        subject, nonce = payload.get("sub"), payload.get("sid")
        issued_at, expires_at, token_id = payload.get("iat"), payload.get("exp"), payload.get("jti")
        now = int(datetime.now(timezone.utc).timestamp())
        # Explicit bounds prevent malformed signed claims from causing database
        # errors, and legacy tokens without an epoch are never accepted.
        if (
            not isinstance(subject, str)
            or not subject.isascii()
            or not subject.isdigit()
            or len(subject) > 10
            or not 0 < int(subject) <= 2147483647
            or not is_valid_session_nonce(nonce)
            or not isinstance(token_id, str)
            or _JTI_PATTERN.fullmatch(token_id) is None
            or type(issued_at) is not int
            or type(expires_at) is not int
            or issued_at > now + 60
            or expires_at <= now
            or expires_at <= issued_at
        ):
            return None
        return AccessTokenClaims(user_id=int(subject), session_nonce=nonce)
    except (JWTError, TypeError, ValueError, OverflowError):
        return None
