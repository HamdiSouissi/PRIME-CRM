"""Protect persistent AI provider credentials with authenticated encryption.

The key is domain-separated from the JWT and Redis keys and bound to the
company and provider record. Existing plaintext credentials are not read or
silently migrated: an administrator must replace them explicitly.
"""

import base64
import hashlib
import hmac
import re

from cryptography.fernet import Fernet, InvalidToken

from ...config import settings


CREDENTIAL_PREFIX = "fernet:v1:"
CREDENTIAL_ERROR = "Clé IA non chiffrée ou illisible : remplacez-la dans les paramètres IA."


class AICredentialError(ValueError):
    """A fixed, non-sensitive error for an unavailable provider credential."""


def _cipher(company_id: int, provider_id: int) -> Fernet:
    if type(company_id) is not int or company_id < 1 or type(provider_id) is not int or provider_id < 1:
        raise AICredentialError(CREDENTIAL_ERROR)
    context = f"primecrm:ai:provider-credential:fernet:v1:{company_id}:{provider_id}".encode("ascii")
    key = hmac.new(settings.SECRET_KEY.encode("utf-8"), context, hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_credential(value: str | None, company_id: int, provider_id: int) -> str | None:
    """Encrypt a newly supplied credential, never returning its plaintext."""
    if not value:
        return None
    try:
        token = _cipher(company_id, provider_id).encrypt(value.encode("utf-8"))
    except (UnicodeError, ValueError):
        raise AICredentialError("Clé IA invalide.") from None
    return CREDENTIAL_PREFIX + token.decode("ascii")


def decrypt_credential(value: str | None, company_id: int, provider_id: int) -> str | None:
    """Decrypt only versioned credentials bound to this company and record."""
    if not value:
        return None
    if not value.startswith(CREDENTIAL_PREFIX):
        raise AICredentialError(CREDENTIAL_ERROR)
    try:
        token = value[len(CREDENTIAL_PREFIX):].encode("ascii")
        # Fernet's base64 decoder accepts some non-canonical trailing bytes;
        # reject them rather than treating a modified stored token as valid.
        if not re.fullmatch(rb"[A-Za-z0-9_-]+={0,2}", token):
            raise ValueError("Invalid token encoding")
        decoded = base64.b64decode(token, altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(decoded) != token:
            raise ValueError("Non-canonical token encoding")
        plaintext = _cipher(company_id, provider_id).decrypt(token).decode("utf-8")
        if not plaintext:
            raise ValueError("Empty credential")
        return plaintext
    except (InvalidToken, UnicodeError, ValueError):
        raise AICredentialError(CREDENTIAL_ERROR) from None


def credential_needs_reset(value: str | None, company_id: int, provider_id: int) -> bool:
    if not value:
        return False
    try:
        decrypt_credential(value, company_id, provider_id)
    except AICredentialError:
        return True
    return False
