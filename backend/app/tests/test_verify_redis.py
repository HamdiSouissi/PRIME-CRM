"""Safe, interactive verification of an isolated Upstash Redis database."""

import getpass
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import warnings

import pytest
from redis.exceptions import AuthenticationError, ConnectionError, RedisError, TimeoutError

from app import verify_redis


# Fake credentials and hosts: no real provider or database is contacted here.
FAKE_URL = "rediss://default:fake-test-token@unit-test.upstash.io:6379/0"
FAKE_ENDPOINT = "unit-test.upstash.io:6379"
BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("url", [
    "",
    "redis://default:fake-test-token@unit-test.upstash.io:6379/0",
    "rediss://unit-test.upstash.io:6379/0",
    "rediss://default:fake-test-token@other.example:6379/0",
    "https://unit-test.upstash.io",
    "rediss://default:fake-test-token@unit-test.upstash.io:bad/0",
    "rediss://default:fake-test-token@unit-test.upstash.io:6379/1",
    "rediss://default:fake-test-token@unit-test.upstash.io:6379/0?ssl_check_hostname=false",
    "rediss://default:fake-test-token@unit-test.upstash.io:6379/0#fragment",
    " rediss://default:fake-test-token@unit-test.upstash.io:6379/0",
])
def test_rejects_unsafe_or_non_upstash_urls(url):
    assert not verify_redis.is_upstash_tcp_url(url)


def test_accepts_authenticated_tls_upstash_urls():
    assert verify_redis.is_upstash_tcp_url(FAKE_URL)
    assert verify_redis.is_upstash_tcp_url("rediss://:fake-test-token@unit-test.upstash.io")


@pytest.mark.parametrize("value", [
    FAKE_URL,
    "https://unit-test.upstash.io",
    "default:fake-test-token@unit-test.upstash.io:6379",
    "unit-test.upstash.io:bad",
    "unit-test.upstash.io:0",
    "unit-test.upstash.io:65536",
    "unit-test.upstash.io/0",
    "other.example:6379",
    "unit-test.upstash.io?ssl=false",
    " unit-test.upstash.io",
])
def test_tls_endpoint_rejects_urls_credentials_and_bad_hosts(value):
    assert verify_redis.parse_upstash_endpoint(value) is None


def test_tls_endpoint_accepts_only_a_hostname_and_optional_port():
    assert verify_redis.parse_upstash_endpoint("unit-test.upstash.io") == ("unit-test.upstash.io", 6379)
    assert verify_redis.parse_upstash_endpoint("unit-test.upstash.io:16379") == ("unit-test.upstash.io", 16379)


def test_main_does_not_disclose_url_on_connection_failure(monkeypatch, capsys):
    monkeypatch.setattr(verify_redis.getpass, "getpass", lambda prompt: FAKE_URL)

    def broken_store(url, secret, prefix):
        raise RedisError(f"fake provider returned {url} and {secret}")

    monkeypatch.setattr(verify_redis, "_make_test_store", broken_store)
    assert verify_redis.main() == 1
    output = capsys.readouterr()
    assert "TEST_REDIS_NON_VALIDE" in output.out
    assert "fake-test-token" not in output.out + output.err
    assert "unit-test.upstash.io" not in output.out + output.err


@pytest.mark.parametrize(("error", "expected"), [
    (AuthenticationError("fake-secret-value"), "authentification refusée"),
    (TimeoutError("fake-secret-value"), "délai réseau dépassé"),
    (ConnectionError("CERTIFICATE_VERIFY_FAILED fake-secret-value"), "certificat TLS"),
    (ConnectionError("fake-secret-value"), "connexion réseau ou TLS"),
    (RedisError("fake-secret-value"), "opération Redis refusée"),
    (verify_redis.ProbeError("fake-secret-value"), "vérification du cache"),
])
def test_error_hints_are_actionable_and_sanitized(error, expected):
    hint = verify_redis.safe_error_hint(error)
    assert expected in hint
    assert "fake-secret-value" not in hint


def test_main_rejects_unmasked_input_without_reading_a_secret(monkeypatch, capsys):
    def unsafe_prompt(prompt):
        warnings.warn("terminal may echo input", getpass.GetPassWarning)
        raise AssertionError("A warning must abort before input")

    monkeypatch.setattr(verify_redis.getpass, "getpass", unsafe_prompt)
    assert verify_redis.main() == 1
    assert "Saisie masquée indisponible" in capsys.readouterr().out


def test_unrecognized_cli_arguments_never_echo_credentials(capsys):
    assert verify_redis.main([FAKE_URL]) == 2
    output = capsys.readouterr().out
    assert "Option non reconnue" in output
    assert "fake-test-token" not in output and "unit-test.upstash.io" not in output


def test_tls_diagnostic_mode_does_not_invoke_redis(monkeypatch, capsys):
    monkeypatch.setattr(verify_redis.getpass, "getpass", lambda prompt: FAKE_ENDPOINT)

    def fake_diagnostic(endpoint):
        assert endpoint == ("unit-test.upstash.io", 6379)
        print("RESULTAT_TLS=SUCCES")
        return 0

    def must_not_connect_to_redis(*args, **kwargs):
        pytest.fail("The TLS-only mode must not instantiate a Redis client")

    monkeypatch.setattr(verify_redis, "diagnose_tls", fake_diagnostic)
    monkeypatch.setattr(verify_redis, "_make_test_store", must_not_connect_to_redis)
    assert verify_redis.main(["--tls-diagnostic"]) == 0
    output = capsys.readouterr().out
    assert "RESULTAT_TLS=SUCCES" in output
    assert "fake-test-token" not in output and "unit-test.upstash.io" not in output


def test_tls_diagnostic_rejects_a_full_url_without_echoing_it(monkeypatch, capsys):
    monkeypatch.setattr(verify_redis.getpass, "getpass", lambda prompt: FAKE_URL)
    assert verify_redis.main(["--tls-diagnostic"]) == 1
    output = capsys.readouterr().out
    assert "Format invalide" in output
    assert "fake-test-token" not in output and "unit-test.upstash.io" not in output


@pytest.mark.parametrize(("code", "category"), [
    (10, "CERTIFICAT_EXPIRE"),
    (19, "AUTOSIGNE_DANS_LA_CHAINE"),
    (20, "AUTORITE_OU_CHAINE_NON_RECONNUE"),
    (62, "NOM_HOTE_INCORRECT"),
    (999, "AUTRE_OU_INCONNUE"),
])
def test_tls_diagnostic_returns_only_safe_certificate_details(monkeypatch, capsys, code, category):
    class FakeSocket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def send(self, *args): pytest.fail("No Redis credentials or commands may be sent")
        def sendall(self, *args): pytest.fail("No Redis credentials or commands may be sent")

    class FakeContext:
        check_hostname = False
        verify_mode = None

        def cert_store_stats(self): return {"x509_ca": 42}
        def wrap_socket(self, connection, server_hostname):
            assert server_hostname == "unit-test.upstash.io"
            error = ssl.SSLCertVerificationError("fake-test-token and private hostname")
            error.verify_code = code
            raise error

    def connection(address, timeout):
        assert address == ("unit-test.upstash.io", 6379)
        assert timeout == 5
        return FakeSocket()

    monkeypatch.setenv("SSL_CERT_FILE", "/private/fake-secret.pem")
    monkeypatch.setenv("SSLKEYLOGFILE", "/private/fake-tls-keys.log")
    context = FakeContext()
    monkeypatch.setattr(verify_redis.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(verify_redis.socket, "create_connection", connection)
    assert verify_redis.diagnose_tls(("unit-test.upstash.io", 6379)) == 1
    assert context.check_hostname is True and context.verify_mode == ssl.CERT_REQUIRED
    output = capsys.readouterr().out
    assert "CERTIFICATS_CA_CHARGES=42" in output
    assert "CERTIFICAT_REQUIS=OUI" in output and "VERIFICATION_NOM_HOTE=OUI" in output
    assert "SSL_CERT_FILE_DEFINI=OUI" in output
    assert f"CODE_VERIFICATION_TLS={code}" in output
    assert f"CATEGORIE_TLS={category}" in output
    assert "SSLKEYLOGFILE" not in os.environ
    assert "fake-test-token" not in output
    assert "fake-secret.pem" not in output and "fake-tls-keys.log" not in output
    assert "unit-test.upstash.io" not in output


def test_tls_diagnostic_dns_failure_is_sanitized(monkeypatch, capsys):
    def fail_dns(*args, **kwargs):
        raise socket.gaierror("private host fake-test-token")

    monkeypatch.setattr(verify_redis.socket, "create_connection", fail_dns)
    assert verify_redis.diagnose_tls(("unit-test.upstash.io", 6379)) == 1
    output = capsys.readouterr().out
    assert "RESULTAT_TLS=ECHEC_DNS" in output
    assert "fake-test-token" not in output and "unit-test.upstash.io" not in output


def test_store_factory_ignores_local_dotenv_and_inherited_database_urls(tmp_path):
    (tmp_path / ".env").write_text(
        "APP_ENV=broken\nDATABASE_URL=postgresql://fake-user:fake-secret@example.invalid/unused\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(BACKEND_DIR),
        "APP_ENV": "broken",
        "DATABASE_URL": "postgresql://fake-user:fake-secret@example.invalid/unused",
        "REDIS_URL": "rediss://default:fake-secret@example.invalid/0",
        "LOGIN_LIMIT_SCOPE": "inherited-invalid",
        "PUBLIC_API_ORIGIN": "not-an-origin",
    })
    script = """
from app.verify_redis import _make_test_store
store = _make_test_store(
    'rediss://default:fake-test-token@unit-test.upstash.io:6379/0',
    'test-only-signing-key-abcdefghijklmnopqrstuvwxyz0123456789',
    'primecrm-probe-test',
)
from app.services.redis_store import CertifiTLSConnection
from app.config import settings
assert settings.LOGIN_LIMIT_SCOPE == 'ip' and settings.PUBLIC_API_ORIGIN == ''
assert store.client.connection_pool.connection_class is CertifiTLSConnection
store.close()
print('isolated settings OK')
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "isolated settings OK" in result.stdout
    assert "fake-secret" not in result.stdout + result.stderr
    assert "fake-test-token" not in result.stdout + result.stderr


def test_verify_store_uses_only_test_keys_and_cleans_up(redis_store, capsys):
    # The fixture provides only a disposable loopback Redis and random prefix.
    sentinel = f"{redis_store.prefix}:other-{secrets.token_hex(8)}"
    redis_store.client.set(sentinel, "unrelated", ex=90)
    assert verify_redis.verify_store(redis_store)
    assert redis_store.client.get(sentinel) == "unrelated"
    output = capsys.readouterr().out
    assert "TLS, authentification et écriture : OK" in output
    assert "Cache chiffré et expiration : OK" in output
    assert "Compteur Lua partagé : OK" in output
    assert "Clés de test supprimées : OK" in output
    assert "probe@example.invalid" not in output


def test_failed_cleanup_leaves_only_short_lived_keys(redis_store, monkeypatch, capsys):
    with monkeypatch.context() as patch:
        def cannot_delete(key):
            raise RedisError("fake-secret-value")

        patch.setattr(redis_store.client, "delete", cannot_delete)
        assert not verify_redis.verify_store(redis_store)
    output = capsys.readouterr().out
    assert "Nettoyage non confirmé" in output
    assert "fake-secret-value" not in output
    for key in redis_store.client.scan_iter(match=f"{redis_store.prefix}:*"):
        assert 0 < redis_store.client.ttl(key) <= 60
