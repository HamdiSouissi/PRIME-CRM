"""Real TLS on loopback only; all names, certificates, credentials and DNS are fictitious."""

import datetime as dt
import socketserver
import ssl
import threading

import anyio
import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.config import settings
from app.services.ai_service import egress


HOSTNAME = "provider.example.invalid"
PUBLIC_IP = "93.184.216.34"
FAKE_KEY = "sk-tls-test-not-a-real-credential-123456"


def make_certificates(directory, certificate_hostname):
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Ephemeral test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, certificate_hostname)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(server_name).issuer_name(ca_name).public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(certificate_hostname)]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    ca_path, cert_path, key_path = (directory / name for name in ("test-ca.pem", "server.pem", "server.key"))
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(server_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ))
    return ca_path, cert_path, key_path


class LocalTLSServer:
    def __init__(self, directory, certificate_hostname, response):
        self.ca_path, cert_path, key_path = make_certificates(directory, certificate_hostname)
        self.sni = []
        self.requests = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        context.set_servername_callback(lambda sock, name, ctx: self.sni.append(name))
        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    with context.wrap_socket(self.request, server_side=True) as connection:
                        connection.settimeout(3)
                        request = b""
                        while b"\r\n\r\n" not in request and len(request) < 65536:
                            chunk = connection.recv(4096)
                            if not chunk:
                                return
                            request += chunk
                        owner.requests.append(request)
                        connection.sendall(response)
                except (ssl.SSLError, OSError):
                    # Expected for negative certificate tests; no real credentials or network.
                    pass

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


@pytest.fixture
def server_factory(tmp_path):
    servers = []

    def create(hostname=HOSTNAME, response=b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"data":[]}'):
        directory = tmp_path / str(len(servers))
        directory.mkdir()
        server = LocalTLSServer(directory, hostname, response)
        servers.append(server)
        return server

    yield create
    for server in servers:
        server.close()


def setup_local_dial(monkeypatch, server, port=443, trust_test_ca=True):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "AI_ALLOW_LOCAL_OLLAMA", False)
    origin = f"https://{HOSTNAME}" + (f":{port}" if port != 443 else "")
    monkeypatch.setattr(settings, "AI_ALLOWED_ORIGINS", origin)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    attempted = []

    async def fake_dns(target):
        assert target.hostname == HOSTNAME
        return [PUBLIC_IP]

    real_connect = anyio.connect_tcp

    async def connect_only_loopback(*args, **kwargs):
        # Observe the destination requested by HTTPX before directing this test to the local socket.
        assert not args
        attempted.append((kwargs["remote_host"], kwargs["remote_port"]))
        assert (kwargs["remote_host"], kwargs["remote_port"]) == (PUBLIC_IP, port)
        kwargs["remote_host"], kwargs["remote_port"] = "127.0.0.1", server.port
        return await real_connect(**kwargs)

    monkeypatch.setattr(egress, "_resolve_ipv4", fake_dns)
    monkeypatch.setattr(anyio, "connect_tcp", connect_only_loopback)
    if trust_test_ca:
        monkeypatch.setattr(egress, "_verified_tls_context", lambda: ssl.create_default_context(cafile=str(server.ca_path)))
    return origin + "/v1", attempted


@pytest.mark.asyncio
@pytest.mark.parametrize("port", [443, 8443])
async def test_real_tls_dials_validated_ip_with_original_host_sni_and_certificate(monkeypatch, server_factory, port):
    server = server_factory()
    base, attempted = setup_local_dial(monkeypatch, server, port=port)
    result = await egress.request_provider(base, ollama=False, method="GET", endpoint="/models", api_key=FAKE_KEY)
    assert result.status_code == 200 and result.json() == {"data": []}
    assert attempted == [(PUBLIC_IP, port)]
    assert server.sni == [HOSTNAME]
    assert len(server.requests) == 1
    request = server.requests[0].decode("ascii")
    expected_host = HOSTNAME + (f":{port}" if port != 443 else "")
    assert request.startswith("GET /v1/models HTTP/1.1\r\n")
    assert f"host: {expected_host}\r\n" in request.lower()
    assert f"authorization: bearer {FAKE_KEY.lower()}\r\n" in request.lower()


@pytest.mark.asyncio
async def test_real_tls_rejects_wrong_hostname_and_never_sends_http(monkeypatch, server_factory):
    server = server_factory(hostname="different.example.invalid")
    base, attempted = setup_local_dial(monkeypatch, server)
    with pytest.raises(httpx.ConnectError):
        await egress.request_provider(base, ollama=False, method="GET", endpoint="/models", api_key=FAKE_KEY)
    assert attempted == [(PUBLIC_IP, 443)] and server.sni == [HOSTNAME]
    assert server.requests == []


@pytest.mark.asyncio
async def test_real_tls_rejects_untrusted_ca_and_never_sends_http(monkeypatch, server_factory):
    server = server_factory()
    base, attempted = setup_local_dial(monkeypatch, server, trust_test_ca=False)
    with pytest.raises(httpx.ConnectError):
        await egress.request_provider(base, ollama=False, method="GET", endpoint="/models", api_key=FAKE_KEY)
    assert attempted == [(PUBLIC_IP, 443)] and server.sni == [HOSTNAME]
    assert server.requests == []


@pytest.mark.asyncio
async def test_real_tls_never_follows_redirect_to_link_local(monkeypatch, server_factory):
    server = server_factory(response=(
        b"HTTP/1.1 302 Found\r\nLocation: http://169.254.169.254/latest/meta-data/\r\n"
        b"Content-Length: 0\r\nConnection: close\r\n\r\n"
    ))
    base, attempted = setup_local_dial(monkeypatch, server)
    result = await egress.request_provider(base, ollama=False, method="GET", endpoint="/models", api_key=FAKE_KEY)
    assert result.status_code == 302
    assert attempted == [(PUBLIC_IP, 443)] and len(server.requests) == 1


def test_production_tls_context_requires_verification_and_disables_key_logging(monkeypatch, tmp_path):
    keylog = tmp_path / "forbidden-keylog.txt"
    monkeypatch.setenv("SSLKEYLOGFILE", str(keylog))
    context = egress._verified_tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.keylog_filename is None
    assert not keylog.exists()
