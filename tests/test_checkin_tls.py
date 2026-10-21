"""Worker TLS policy and a real local CONNECT tunnel, with synthetic certificates."""
import select
import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from stu_checkin.vendor.duifene.api import DuifeneApi
from stu_checkin.vendor.duifene.bridge import Bridge
from stu_checkin.vendor.duifene.rate_limit import RateLimiter
from stu_checkin.vendor.duifene.settings import Settings
from stu_checkin.vendor.duifene.signalr import DuifeneMessageHub


@pytest.mark.parametrize("proxy", ["", "127.0.0.1:8080", "http://127.0.0.1:8080"])
def test_proxy_configuration_and_legacy_constructor_never_disable_verification(proxy):
    settings = Settings(proxy_url=proxy, verify_tls=False)
    assert settings.verify_tls is True
    assert settings.apply({"proxy_url": proxy}) == "" and settings.verify_tls is True
    assert settings.persistable_values()["verify_tls"] is True
    assert settings.apply({"verify_tls": False}) and settings.verify_tls is True
    expected = {"http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080"} if proxy else None
    assert settings.proxies == expected


def test_old_persisted_false_and_mutated_settings_cannot_downgrade_bridge_session():
    store = SimpleNamespace(load_settings=lambda: {"proxy_url": "127.0.0.1:8080", "verify_tls": False})
    settings = Settings()
    settings.verify_tls = False
    bridge = Bridge(settings, store=store)  # Does not bootstrap, start threads or read credentials.
    try:
        assert settings.verify_tls is True and bridge._session.verify is True
        assert bridge._session.proxies["https"] == "http://127.0.0.1:8080"
        settings.verify_tls = False
        bridge._apply_session_config(bridge._session)
        assert settings.verify_tls is True and bridge._api.verify is True
    finally:
        bridge._session.close()


def test_signalr_https_and_websocket_enforce_certificate_and_hostname_with_a_proxy(monkeypatch):
    connection = Mock()
    monkeypatch.setattr("stu_checkin.vendor.duifene.signalr.websocket.create_connection", connection)
    hub = DuifeneMessageHub(verify=False, proxies={"https": "http://127.0.0.1:8080"})
    try:
        assert hub.verify is True and hub._session.verify is True
        hub._open_ws("SYNTHETIC_CONNECTION_TOKEN")
        options = connection.call_args.kwargs
        assert options["sslopt"] == {"cert_reqs": ssl.CERT_REQUIRED, "check_hostname": True}
        assert options["http_proxy_host"] == "127.0.0.1" and options["http_proxy_port"] == 8080
    finally:
        hub._session.close()


@pytest.mark.parametrize("trusted,matching_hostname", [(False, True), (True, False), (True, True)])
def test_proxy_connect_preserves_real_certificate_and_hostname_validation(tmp_path, monkeypatch, trusted, matching_hostname):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-local-test")])
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(UTC) - timedelta(days=1))
                   .not_valid_after(datetime.now(UTC) + timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .add_extension(x509.SubjectAlternativeName([x509.DNSName(
                       "localhost" if matching_hostname else "synthetic-other.invalid")]), critical=False)
                   .sign(key, hashes.SHA256()))
    cert_file, key_file = tmp_path / "synthetic-cert.pem", tmp_path / "synthetic-key.pem"
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    requests_seen, tunnels = [], []

    class Target(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            requests_seen.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    target = HTTPServer(("127.0.0.1", 0), Target)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    target.socket = context.wrap_socket(target.socket, server_side=True)
    target_thread = threading.Thread(target=target.serve_forever, daemon=True)
    target_thread.start()

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_CONNECT(self):
            assert self.path == f"localhost:{target.server_port}"
            tunnels.append(self.path)
            with socket.create_connection(("127.0.0.1", target.server_port), timeout=3) as upstream:
                self.send_response(200, "Connection Established")
                self.end_headers()
                sockets = [self.connection, upstream]
                while True:
                    readable, _, _ = select.select(sockets, [], [], 3)
                    if not readable:
                        return
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        destination = upstream if source is self.connection else self.connection
                        destination.sendall(data)

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    settings = Settings(host=f"https://localhost:{target.server_port}", proxy_url=f"http://127.0.0.1:{proxy.server_port}")
    bridge = Bridge(settings, store=SimpleNamespace(load_settings=lambda: {}))
    if trusted:
        # Existing requests CA-bundle mechanism, scoped only to this test. No OS
        # trust store, environment, real certificate or system proxy is changed.
        monkeypatch.setattr(requests.adapters, "DEFAULT_CA_BUNDLE_PATH", str(cert_file))
    try:
        api = DuifeneApi(bridge._session, settings, RateLimiter(settings))
        if trusted and matching_hostname:
            assert api.login_by_link("A" * 32).status_code == 200
            assert len(requests_seen) == 1
        else:
            with pytest.raises(requests.exceptions.SSLError):
                api.login_by_link("A" * 32)
            assert not requests_seen  # TLS failure occurs before a callback code can be sent.
        assert len(tunnels) == 1 and bridge._session.verify is True
    finally:
        bridge._session.close()
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join(timeout=3)
        target.shutdown()
        target.server_close()
        target_thread.join(timeout=3)
