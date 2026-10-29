"""TLS-only expiry investigation; never send Redis commands or credentials.

Certificate messages observed before a failed verification are untrusted. Only
expiration dates and counts are reported, never certificates or identities.
"""

from datetime import datetime, timezone
import os
import re
import socket
import ssl

from cryptography import x509


# Bounds are intentionally small for this diagnostic; larger chains are
# reported as unavailable rather than being processed or printed.
_MAX_MESSAGE_BYTES = 256 * 1024
_MAX_CERTIFICATES = 16


def _read_u24(data: bytes, position: int) -> tuple[int, int]:
    if position + 3 > len(data):
        raise ValueError("Truncated TLS certificate message")
    return int.from_bytes(data[position:position + 3], "big"), position + 3


def _parse_certificate_message(data: bytes, version: int) -> list[bytes]:
    """Extract peer-sent DER certificates from TLS 1.2 or 1.3, not a verified chain."""
    if len(data) < 7 or len(data) > _MAX_MESSAGE_BYTES or data[0] != 11:
        raise ValueError("Invalid TLS certificate message")
    message_length, pos = _read_u24(data, 1)
    if message_length != len(data) - 4:
        raise ValueError("Invalid handshake length")
    tls13 = int(version) == int(ssl.TLSVersion.TLSv1_3)
    if not tls13 and int(version) != int(ssl.TLSVersion.TLSv1_2):
        raise ValueError("Unsupported TLS version")
    if tls13:
        request_context_length = data[pos]
        pos += 1 + request_context_length
    chain_length, pos = _read_u24(data, pos)
    if chain_length != len(data) - pos:
        raise ValueError("Invalid certificate list length")
    certificates = []
    while pos < len(data):
        certificate_length, pos = _read_u24(data, pos)
        end = pos + certificate_length
        if certificate_length == 0 or end > len(data) or len(certificates) >= _MAX_CERTIFICATES:
            raise ValueError("Invalid or oversized certificate list")
        certificates.append(data[pos:end])
        pos = end
        if tls13:
            if pos + 2 > len(data):
                raise ValueError("Truncated certificate extensions")
            extensions_length = int.from_bytes(data[pos:pos + 2], "big")
            pos += 2 + extensions_length
            if pos > len(data):
                raise ValueError("Invalid certificate extensions")
    if not certificates:
        raise ValueError("Empty certificate list")
    return certificates


class _PresentedCertificateDates:
    """Collect dates only; OpenSSL still rejects any verification failure."""

    def __init__(self):
        self.expirations = None

    def __call__(self, connection, direction, version, content_type, message_type, data):
        # _msg_callback is a private CPython diagnostic hook. It observes the
        # peer's handshake messages before verification; it never authorizes a
        # connection. If unsupported or unparsable, no dates are reported.
        try:
            if direction != "read" or int(content_type) != 22 or int(message_type) != 11:
                return
            certificates = _parse_certificate_message(data, version)
            self.expirations = [x509.load_der_x509_certificate(cert).not_valid_after_utc for cert in certificates]
        except Exception:
            self.expirations = None


def _probe(context: ssl.SSLContext, endpoint: tuple[str, int]) -> tuple[str, int | None]:
    """Perform only a verified handshake; sanitize all network/TLS errors."""
    try:
        host, port = endpoint
        with socket.create_connection((host, port), timeout=5) as connection:
            with context.wrap_socket(connection, server_hostname=host):
                return "SUCCES", None
    except ssl.SSLCertVerificationError as error:
        code = getattr(error, "verify_code", None)
        return "ECHEC_CERTIFICAT", code if type(code) is int and 0 <= code <= 9999 else None
    except socket.gaierror:
        return "ECHEC_DNS", None
    except TimeoutError:
        return "DELAI_DEPASSE", None
    except OSError:
        return "ECHEC_RESEAU_OU_TLS", None
    except Exception:
        return "ERREUR_INATTENDUE", None


def _required_context(*, ca_file: str | None = None) -> ssl.SSLContext:
    # An explicit cafile makes Python load ONLY that CA bundle; the default
    # context uses the OS/OpenSSL defaults. Both require a valid hostname.
    if ca_file is None:
        context = ssl.create_default_context()
    else:
        if not ca_file:
            raise ValueError("An explicit CA bundle cannot be empty")
        context = ssl.create_default_context(cafile=ca_file)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def diagnose_certificate_path(endpoint: tuple[str, int]) -> int:
    """Compare system and certifi trust, without changing application settings."""
    os.environ.pop("SSLKEYLOGFILE", None)
    print(f"HEURE_UTC={datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print("CERTIFICAT_REQUIS=OUI")
    print("VERIFICATION_NOM_HOTE=OUI")

    try:
        system_context = _required_context()
    except Exception:
        print("RESULTAT_CA_SYSTEME=CONTEXTE_TLS_IMPOSSIBLE")
        return 1
    dates = _PresentedCertificateDates()
    try:
        system_context._msg_callback = dates
    except (AttributeError, ValueError, TypeError):
        pass
    system_result, system_code = _probe(system_context, endpoint)
    print(f"RESULTAT_CA_SYSTEME={system_result}")
    if system_result == "ECHEC_CERTIFICAT":
        print(f"CODE_CA_SYSTEME={system_code if system_code is not None else 'INCONNU'}")

    if dates.expirations is None:
        print("CERTIFICATS_PRESENTES=INDISPONIBLES")
    else:
        now = datetime.now(timezone.utc)
        first, *others = dates.expirations
        print("DATES_PRESENTEES_NON_AUTHENTIFIEES=OUI")
        print(f"CERTIFICATS_PRESENTES={len(dates.expirations)}")
        print(f"CERTIFICAT_TERMINAL_EXPIRATION_UTC={first.isoformat(timespec='seconds')}")
        print(f"CERTIFICAT_TERMINAL_EXPIRE={'OUI' if first < now else 'NON'}")
        print(f"AUTRES_CERTIFICATS_PRESENTES_EXPIRES={sum(value < now for value in others)}")

    # certifi is optional: this is an alternative, isolated trust store for
    # comparison only. Missing or outdated certifi is never silently installed.
    try:
        import certifi

        alternative = _required_context(ca_file=certifi.where())
        version = getattr(certifi, "__version__", "")
        version = version if isinstance(version, str) and re.fullmatch(r"\d{4}\.\d{1,2}\.\d{1,2}", version) else "INCONNUE"
    except Exception:
        print("CA_CERTIFI=INDISPONIBLE")
    else:
        print("CA_CERTIFI=DISPONIBLE")
        print(f"VERSION_CERTIFI={version}")
        alternative_result, alternative_code = _probe(alternative, endpoint)
        print(f"RESULTAT_CA_CERTIFI={alternative_result}")
        if alternative_result == "ECHEC_CERTIFICAT":
            print(f"CODE_CA_CERTIFI={alternative_code if alternative_code is not None else 'INCONNU'}")

    # Success requires the application's default trust path to succeed too.
    return 0 if system_result == "SUCCES" else 1
