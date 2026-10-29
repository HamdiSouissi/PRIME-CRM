"""Tests use disposable localhost certificates and never contact Upstash."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import ipaddress
import os
import socket
import socketserver
import ssl
import sys
import threading

import certifi
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app import tls_diagnostic, verify_redis


def _certificates(tmp_path, *, expired_leaf=False, expired_system_ca=False, expired_intermediate=False):
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Private test CA")])

    def ca_certificate(expires):
        return (
            x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
            .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=90)).not_valid_after(expires)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256())
        )

    good_ca = ca_certificate(now + timedelta(days=90))
    system_ca = ca_certificate(now - timedelta(days=1)) if expired_system_ca else good_ca
    issuer, signing_key, extra_chain = ca_name, ca_key, b""
    if expired_intermediate:
        intermediate_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        intermediate_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Private test intermediate")])
        intermediate = (
            x509.CertificateBuilder().subject_name(intermediate_name).issuer_name(ca_name)
            .public_key(intermediate_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=60)).not_valid_after(now - timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        issuer, signing_key = intermediate_name, intermediate_key
        extra_chain = intermediate.public_bytes(serialization.Encoding.PEM)
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (
        x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(issuer).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=10))
        .not_valid_after(now - timedelta(days=1) if expired_leaf else now + timedelta(days=10))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(signing_key, hashes.SHA256())
    )
    system_file, alternate_file = tmp_path / "system-ca.pem", tmp_path / "alternate-ca.pem"
    leaf_file, key_file = tmp_path / "leaf.pem", tmp_path / "private-key.pem"
    system_file.write_bytes(system_ca.public_bytes(serialization.Encoding.PEM))
    alternate_file.write_bytes(good_ca.public_bytes(serialization.Encoding.PEM))
    leaf_file.write_bytes(leaf.public_bytes(serialization.Encoding.PEM) + extra_chain)
    key_file.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return system_file, alternate_file, leaf_file, key_file


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            with self.server.tls_context.wrap_socket(self.request, server_side=True) as connection:
                connection.settimeout(3)
                data = connection.recv(1024)
                if data:
                    self.server.application_data.append(data)
        except (ssl.SSLError, OSError):
            pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


@contextmanager
def _local_tls_server(leaf_file, key_file, version):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = context.maximum_version = version
    context.load_cert_chain(leaf_file, key_file)
    server = _Server(("127.0.0.1", 0), _Handler)
    server.tls_context = context
    server.application_data = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize("version", [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3])
def test_expired_presented_leaf_is_rejected_without_commands(version, tmp_path, monkeypatch, capsys):
    if version is ssl.TLSVersion.TLSv1_3 and not ssl.HAS_TLSv1_3:
        pytest.skip("TLS 1.3 not supported")
    system_file, alternate_file, leaf_file, key_file = _certificates(tmp_path, expired_leaf=True)
    monkeypatch.setenv("SSL_CERT_FILE", str(system_file))
    monkeypatch.setenv("SSLKEYLOGFILE", str(tmp_path / "private-tls-keys.log"))
    monkeypatch.setattr(certifi, "where", lambda: str(alternate_file))
    with _local_tls_server(leaf_file, key_file, version) as server:
        assert tls_diagnostic.diagnose_certificate_path(("localhost", server.server_address[1])) == 1
        output = capsys.readouterr().out
    assert "RESULTAT_CA_SYSTEME=ECHEC_CERTIFICAT" in output and "CODE_CA_SYSTEME=10" in output
    assert "RESULTAT_CA_CERTIFI=ECHEC_CERTIFICAT" in output and "CODE_CA_CERTIFI=10" in output
    assert "DATES_PRESENTEES_NON_AUTHENTIFIEES=OUI" in output
    assert "CERTIFICATS_PRESENTES=1" in output and "CERTIFICAT_TERMINAL_EXPIRE=OUI" in output
    assert "CERTIFICAT_TERMINAL_EXPIRATION_UTC=" in output
    assert "AUTRES_CERTIFICATS_PRESENTES_EXPIRES=0" in output
    assert "localhost" not in output and str(tmp_path) not in output
    assert not server.application_data and "SSLKEYLOGFILE" not in os.environ
    assert not (tmp_path / "private-tls-keys.log").exists()


@pytest.mark.parametrize("version", [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3])
def test_expired_presented_intermediate_is_reported(version, tmp_path, monkeypatch, capsys):
    if version is ssl.TLSVersion.TLSv1_3 and not ssl.HAS_TLSv1_3:
        pytest.skip("TLS 1.3 not supported")
    system_file, alternate_file, leaf_file, key_file = _certificates(tmp_path, expired_intermediate=True)
    monkeypatch.setenv("SSL_CERT_FILE", str(system_file))
    monkeypatch.setattr(certifi, "where", lambda: str(alternate_file))
    with _local_tls_server(leaf_file, key_file, version) as server:
        assert tls_diagnostic.diagnose_certificate_path(("localhost", server.server_address[1])) == 1
        output = capsys.readouterr().out
    assert "CODE_CA_SYSTEME=10" in output and "CODE_CA_CERTIFI=10" in output
    assert "CERTIFICATS_PRESENTES=2" in output and "CERTIFICAT_TERMINAL_EXPIRE=NON" in output
    assert "AUTRES_CERTIFICATS_PRESENTES_EXPIRES=1" in output
    assert not server.application_data and "localhost" not in output


def test_expired_local_trust_anchor_is_distinguishable_from_presented_leaf(tmp_path, monkeypatch, capsys):
    system_file, alternate_file, leaf_file, key_file = _certificates(tmp_path, expired_system_ca=True)
    monkeypatch.setenv("SSL_CERT_FILE", str(system_file))
    monkeypatch.setattr(certifi, "where", lambda: str(alternate_file))
    with _local_tls_server(leaf_file, key_file, ssl.TLSVersion.TLSv1_2) as server:
        assert tls_diagnostic.diagnose_certificate_path(("localhost", server.server_address[1])) == 1
        output = capsys.readouterr().out
    assert "RESULTAT_CA_SYSTEME=ECHEC_CERTIFICAT" in output and "CODE_CA_SYSTEME=10" in output
    assert "CERTIFICAT_TERMINAL_EXPIRE=NON" in output and "AUTRES_CERTIFICATS_PRESENTES_EXPIRES=0" in output
    assert "RESULTAT_CA_CERTIFI=SUCCES" in output
    assert not server.application_data and "localhost" not in output


def test_wrong_hostname_is_not_accepted(tmp_path, monkeypatch, capsys):
    system_file, alternate_file, leaf_file, key_file = _certificates(tmp_path)
    monkeypatch.setenv("SSL_CERT_FILE", str(system_file))
    monkeypatch.setattr(certifi, "where", lambda: str(alternate_file))
    with _local_tls_server(leaf_file, key_file, ssl.TLSVersion.TLSv1_2) as server:
        assert tls_diagnostic.diagnose_certificate_path((str(ipaddress.ip_address("127.0.0.1")), server.server_address[1])) == 1
        output = capsys.readouterr().out
    assert "VERIFICATION_NOM_HOTE=OUI" in output
    assert "RESULTAT_CA_SYSTEME=ECHEC_CERTIFICAT" in output and "CODE_CA_SYSTEME=64" in output
    assert "RESULTAT_CA_CERTIFI=ECHEC_CERTIFICAT" in output and "CODE_CA_CERTIFI=64" in output
    assert not server.application_data and "127.0.0.1" not in output


def test_missing_certifi_is_safe_and_does_not_disable_system_validation(tmp_path, monkeypatch, capsys):
    system_file, _, leaf_file, key_file = _certificates(tmp_path)
    monkeypatch.setenv("SSL_CERT_FILE", str(system_file))
    monkeypatch.setitem(sys.modules, "certifi", None)
    with _local_tls_server(leaf_file, key_file, ssl.TLSVersion.TLSv1_2) as server:
        assert tls_diagnostic.diagnose_certificate_path(("localhost", server.server_address[1])) == 0
        output = capsys.readouterr().out
    assert "RESULTAT_CA_SYSTEME=SUCCES" in output and "CA_CERTIFI=INDISPONIBLE" in output
    assert not server.application_data


@pytest.mark.parametrize("data", [b"", b"\x0b\x00\x00\x04\x00\x00\x01\xff", b"\x0c\x00\x00\x03\x00\x00\x00"])
def test_malformed_or_unknown_handshakes_are_not_interpreted(data):
    with pytest.raises(ValueError):
        tls_diagnostic._parse_certificate_message(data, ssl.TLSVersion.TLSv1_2)


def test_cli_detailed_diagnostic_rejects_a_url_without_echo(monkeypatch, capsys):
    monkeypatch.setattr(
        verify_redis.getpass, "getpass",
        lambda prompt: "rediss://default:fake-secret@unit-test.upstash.io:6379/0",
    )
    assert verify_redis.main(["--tls-certificate-details"]) == 1
    output = capsys.readouterr().out
    assert "Format invalide" in output
    assert "fake-secret" not in output and "unit-test.upstash.io" not in output


def test_cli_detailed_diagnostic_uses_only_the_endpoint(monkeypatch, capsys):
    monkeypatch.setattr(verify_redis.getpass, "getpass", lambda prompt: "unit-test.upstash.io")
    monkeypatch.setattr(tls_diagnostic, "diagnose_certificate_path", lambda endpoint: 0 if endpoint == ("unit-test.upstash.io", 6379) else 1)
    monkeypatch.setattr(verify_redis, "_make_test_store", lambda *args: pytest.fail("Redis is not used"))
    assert verify_redis.main(["--tls-certificate-details"]) == 0
    output = capsys.readouterr().out
    assert "unit-test.upstash.io" not in output
