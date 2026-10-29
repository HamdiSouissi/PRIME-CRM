"""Interactively check a dedicated Upstash database without reading CRM data.

The URL is requested with echo disabled and is never written to a file or log.
Only two randomly namespaced keys with short TTLs are created and deleted.
"""

from datetime import datetime, timezone
import getpass
import os
import secrets
import socket
import ssl
import sys
import tempfile
import warnings
from urllib.parse import urlsplit


class ProbeError(Exception):
    """A verification failed; error messages must not include credentials."""


def is_upstash_tcp_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
        return bool(
            parsed.scheme == "rediss"
            and parsed.hostname
            and parsed.hostname.lower().endswith(".upstash.io")
            and parsed.password
            and (port is None or 0 < port <= 65535)
            and parsed.path in {"", "/0"}
            and not parsed.query
            and not parsed.fragment
            and not any(character.isspace() for character in value)
        )
    except ValueError:
        return False


def parse_upstash_endpoint(value: str) -> tuple[str, int] | None:
    """Accept only a hostname and optional port, never a URL or token."""
    try:
        parsed = urlsplit(f"rediss://{value}")
        port = parsed.port
        if (
            not parsed.hostname
            or not parsed.hostname.lower().endswith(".upstash.io")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or any(character.isspace() for character in value)
            or (port is not None and not 0 < port <= 65535)
        ):
            return None
        return parsed.hostname, port or 6379
    except ValueError:
        return None


def _make_test_store(url: str, secret: str, prefix: str):
    # Do not read a developer's .env or inherit their database/Redis URLs.
    # This is a short-lived process: it never opens a PostgreSQL connection.
    # SSLKEYLOGFILE would log TLS session secrets; this process does not need it.
    os.environ.pop("SSLKEYLOGFILE", None)
    os.environ.update({
        "APP_ENV": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "REDIS_URL": "redis://127.0.0.1:1/0",
        "SECRET_KEY": secret,
        "ALLOW_PUBLIC_REGISTRATION": "false",
        "CORS_ORIGINS": "",
    })
    previous_directory = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="primecrm-redis-check-") as directory:
        try:
            os.chdir(directory)
            from .config import Settings
            from .services.redis_store import create_redis_store
        finally:
            os.chdir(previous_directory)

    # Validate the same Redis URL constraints used in production, with a
    # fictitious database URL; validate_runtime only parses it, never connects.
    configuration = Settings(
        _env_file=None,
        APP_ENV="production",
        DATABASE_URL="postgresql://test@127.0.0.1/unused",
        REDIS_URL=url,
        SECRET_KEY=secret,
        ALLOW_PUBLIC_REGISTRATION=False,
        CORS_ORIGINS="",
    )
    configuration.validate_runtime()
    return create_redis_store(url, secret, prefix)


def verify_store(store) -> bool:
    """Use only keys reserved under a random prefix; return cleanup status."""
    company_id = 1  # Fictitious; the namespace and HMAC secret are random.
    identifier = "probe@example.invalid"
    login_key = store._login_key(identifier)
    stage_key = store._stage_key(company_id)
    owned_keys = []
    cleanup_ok = True

    try:
        # Reserve keys using NX, each with a TTL even if the response is lost.
        # The preseeded counter expires after 60 seconds under normal conditions.
        if not store.client.set(login_key, "0", ex=60, nx=True):
            raise ProbeError("Could not reserve a test key")
        owned_keys.append(login_key)
        print("TLS, authentification et écriture : OK")

        if not store.client.set(stage_key, "temporary", ex=30, nx=True):
            raise ProbeError("Could not reserve a test key")
        owned_keys.append(stage_key)
        store.set_stage_outcomes(company_id, [101], [202])
        encrypted = store.client.get(stage_key)
        if (
            store.get_stage_outcomes(company_id) != ([101], [202])
            or not encrypted
            or '"company_id"' in encrypted
            or not 0 < store.client.ttl(stage_key) <= 30
        ):
            raise ProbeError("Cache verification failed")
        print("Cache chiffré et expiration : OK")

        # The same Lua script as the application runs, isolated from real users.
        # The 60-second counter is pre-created to bound the test key lifetime.
        store.record_login(identifier)
        store.record_login(identifier)
        if store.client.get(login_key) != "2" or not 0 < store.client.ttl(login_key) <= 60:
            raise ProbeError("Login counter verification failed")
        print("Compteur Lua partagé : OK")
    finally:
        # Never scan, flush, or delete keys outside this run's random namespace.
        for key in owned_keys:
            try:
                store.client.delete(key)
            except Exception:
                cleanup_ok = False
        if owned_keys:
            if cleanup_ok:
                print("Clés de test supprimées : OK")
            else:
                print("Nettoyage non confirmé : les clés de test ont été créées avec une expiration.")
    return cleanup_ok


def safe_error_hint(error: Exception) -> str:
    """Classify errors without returning exception text, hostnames or secrets."""
    from redis.exceptions import AuthenticationError, ConnectionError, RedisError, TimeoutError

    if isinstance(error, AuthenticationError):
        return "authentification refusée ; vérifiez l'URL TCP dans la console Upstash."
    if isinstance(error, TimeoutError):
        return "délai réseau dépassé ; vérifiez votre connexion et le pare-feu."
    if isinstance(error, ConnectionError):
        details = str(error).casefold().replace("_", " ")  # inspected locally, never logged or returned
        if "certificate verify failed" in details or "hostname mismatch" in details:
            return "certificat TLS ou nom d'hôte non vérifié ; vérifiez les certificats système."
        return "connexion réseau ou TLS impossible ; vérifiez DNS et pare-feu."
    if isinstance(error, RedisError):
        return "opération Redis refusée ; vérifiez la disponibilité et les quotas Free."
    if isinstance(error, ProbeError):
        return "vérification du cache ou du compteur incomplète."
    if isinstance(error, ValueError):
        return "configuration Redis invalide."
    return "erreur inattendue pendant la vérification."


# OpenSSL verification codes, deliberately mapped to fixed strings. Never
# display verify_message: it can contain the user's private Redis hostname.
TLS_VERIFY_CATEGORIES = {
    7: "SIGNATURE_NON_VERIFIEE",
    9: "CERTIFICAT_PAS_ENCORE_VALIDE",
    10: "CERTIFICAT_EXPIRE",
    18: "CERTIFICAT_AUTOSIGNE_NON_RECONNU",
    19: "AUTOSIGNE_DANS_LA_CHAINE",
    20: "AUTORITE_OU_CHAINE_NON_RECONNUE",
    21: "CHAINE_DE_CERTIFICATS_NON_VERIFIEE",
    23: "CERTIFICAT_REVOQUE",
    62: "NOM_HOTE_INCORRECT",
    64: "ADRESSE_IP_INCORRECTE",
}


def diagnose_tls(endpoint: tuple[str, int]) -> int:
    """Check TLS only: no Redis AUTH, commands, tokens, or database writes."""
    os.environ.pop("SSLKEYLOGFILE", None)
    print(f"HEURE_UTC={datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print(f"SSL_CERT_FILE_DEFINI={'OUI' if os.environ.get('SSL_CERT_FILE') else 'NON'}")
    print(f"SSL_CERT_DIR_DEFINI={'OUI' if os.environ.get('SSL_CERT_DIR') else 'NON'}")
    try:
        context = ssl.create_default_context()
        # State the requirements explicitly; neither setting may be disabled.
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        print(f"CERTIFICATS_CA_CHARGES={context.cert_store_stats()['x509_ca']}")
        print("CERTIFICAT_REQUIS=OUI")
        print("VERIFICATION_NOM_HOTE=OUI")
    except Exception:
        print("RESULTAT_TLS=CONTEXTE_TLS_IMPOSSIBLE")
        return 1

    try:
        host, port = endpoint
        with socket.create_connection((host, port), timeout=5) as connection:
            with context.wrap_socket(connection, server_hostname=host):
                # No Redis command or credential is ever sent on this socket.
                print("RESULTAT_TLS=SUCCES")
                return 0
    except ssl.SSLCertVerificationError as error:
        code = getattr(error, "verify_code", None)
        code = code if type(code) is int and 0 <= code <= 9999 else None
        print("RESULTAT_TLS=ECHEC_CERTIFICAT")
        print(f"CODE_VERIFICATION_TLS={code if code is not None else 'INCONNU'}")
        print(f"CATEGORIE_TLS={TLS_VERIFY_CATEGORIES.get(code, 'AUTRE_OU_INCONNUE')}")
        return 1
    except socket.gaierror:
        print("RESULTAT_TLS=ECHEC_DNS")
    except TimeoutError:
        print("RESULTAT_TLS=DELAI_DEPASSE")
    except OSError:
        print("RESULTAT_TLS=ECHEC_RESEAU_OU_TLS")
    except Exception:
        print("RESULTAT_TLS=ERREUR_INATTENDUE")
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = [] if argv is None else argv
    if argv not in ([], ["--tls-diagnostic"], ["--tls-certificate-details"]):
        # Never echo command-line arguments, which could contain credentials.
        print("Option non reconnue ; utilisez --tls-diagnostic, --tls-certificate-details ou aucune option.")
        return 2
    tls_only = bool(argv)
    if tls_only:
        print("Diagnostic TLS : aucun token, commande Redis ou authentification n'est nécessaire.")
        print("Copiez uniquement Endpoint depuis Upstash ; ajoutez :port s'il diffère de 6379.")
        prompt = "Endpoint seul, sans URL ni token (saisie masquée) : "
    else:
        print("Test Redis dédié : aucun accès à PostgreSQL, à Neon ou au CRM.")
        print("Copiez l'URL TCP rediss:// depuis Upstash et collez-la à l'invite masquée.")
        prompt = "URL Redis TCP (saisie masquée) : "
    try:
        with warnings.catch_warnings():
            # Never fall back to an echoed prompt when there is no real terminal.
            warnings.simplefilter("error", getpass.GetPassWarning)
            entered = getpass.getpass(prompt)
    except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("Saisie masquée indisponible ou interrompue ; ouvrez un terminal PowerShell.")
        return 1

    if tls_only:
        endpoint = parse_upstash_endpoint(entered)
        entered = ""
        if endpoint is None:
            print("Format invalide : fournissez uniquement l'Endpoint Upstash et, si besoin, son port.")
            return 1
        try:
            if argv == ["--tls-certificate-details"]:
                from .tls_diagnostic import diagnose_certificate_path

                return diagnose_certificate_path(endpoint)
            return diagnose_tls(endpoint)
        except ImportError:
            print("RESULTAT_TLS=DEPENDANCE_INDISPONIBLE")
            return 1
        except KeyboardInterrupt:
            print("RESULTAT_TLS=INTERROMPU")
            return 1
    url = entered
    entered = ""
    if not is_upstash_tcp_url(url):
        print("Format invalide : utilisez l'URL TCP rediss:// authentifiée d'Upstash, sans paramètres.")
        return 1

    store = None
    try:
        secret = secrets.token_urlsafe(48)
        prefix = f"primecrm-probe:{secrets.token_hex(16)}"
        store = _make_test_store(url, secret, prefix)
        if not verify_store(store):
            print("TEST_REDIS_NON_VALIDE : nettoyage non confirmé.")
            return 1
    except ImportError:
        print("TEST_REDIS_NON_VALIDE : une dépendance Python manque ; réinstallez requirements.txt.")
        return 1
    except Exception as error:
        # Exceptions from Redis or TLS can contain credentials or hostnames.
        print(f"TEST_REDIS_NON_VALIDE : {safe_error_hint(error)}")
        return 1
    except KeyboardInterrupt:
        print("TEST_REDIS_NON_VALIDE : test interrompu.")
        return 1
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass
        url = ""

    print("TEST_REDIS_OK : aucune donnée réelle ni base PostgreSQL utilisée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
