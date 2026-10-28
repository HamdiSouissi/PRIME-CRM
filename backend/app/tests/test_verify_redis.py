"""Safe, interactive verification of an isolated Upstash Redis database."""

import getpass
import os
from pathlib import Path
import secrets
import subprocess
import sys
import warnings

import pytest
from redis.exceptions import AuthenticationError, ConnectionError, RedisError, TimeoutError

from app import verify_redis


# Fake credentials and hosts: no real provider or database is contacted here.
FAKE_URL = "rediss://default:fake-test-token@unit-test.upstash.io:6379/0"
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
    })
    script = """
from app.verify_redis import _make_test_store
store = _make_test_store(
    'rediss://default:fake-test-token@unit-test.upstash.io:6379/0',
    'test-only-signing-key-abcdefghijklmnopqrstuvwxyz0123456789',
    'primecrm-probe-test',
)
options = store.client.connection_pool.connection_kwargs
assert options['ssl_cert_reqs'] == 'required'
assert options['ssl_check_hostname'] is True
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
