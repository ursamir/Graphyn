"""F19 (F-02): SSRF-safe egress by default, IP pinning, redirect re-checks."""
from __future__ import annotations

import ipaddress
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.core.trust import egress


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401
        pass

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/redirect-metadata"):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            return
        body = (self.headers.get("Host") or "").encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def local_server(real_threads):
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()


def test_default_blocks_loopback_and_metadata_without_connecting(monkeypatch):
    monkeypatch.delenv("GRAPHYN_HTTP_EGRESS_MODE", raising=False)
    monkeypatch.delenv("GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW", raising=False)
    for url, why in (
        ("http://127.0.0.1:8001/health", "loopback"),
        ("http://169.254.169.254/latest/meta-data/", "metadata"),
        ("http://[::1]:8001/", "loopback"),
        ("http://10.1.2.3/", "private"),
        ("http://192.168.0.1/", "private"),
        ("http://[fd12::1]/", "private"),
        ("http://[fe80::1]/", "metadata"),
        ("http://[::ffff:127.0.0.1]/", "loopback"),
        ("http://metadata.google.internal/", "metadata"),
    ):
        with pytest.raises(egress.HttpEgressError, match=why):
            with egress.egress_client(timeout=2) as c:
                c.get(url)


def test_internal_allow_is_explicit_and_port_scoped(monkeypatch, local_server):
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW", f"127.0.0.1:{local_server}")
    with egress.egress_client(timeout=5) as c:
        r = c.get(f"http://127.0.0.1:{local_server}/ok")
    assert r.status_code == 200
    with pytest.raises(egress.HttpEgressError, match="loopback"):
        egress.validate_http_egress_url(f"http://127.0.0.1:{local_server + 1}/")


def test_metadata_can_never_be_allowlisted(monkeypatch):
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW", "169.254.0.0/16,169.254.169.254")
    with pytest.raises(egress.HttpEgressError, match="cannot be allowlisted"):
        egress.validate_http_egress_url("http://169.254.169.254/")
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_MODE", "trusted")
    with pytest.raises(egress.HttpEgressError, match="cannot be allowlisted"):
        egress.validate_http_egress_url("http://169.254.169.254/")


def test_connect_uses_validated_ip_not_a_second_lookup(monkeypatch, local_server):
    """DNS-rebinding safety: the socket goes to the IP that was validated.

    ``rebind.example.com`` does not exist in real DNS; the request only
    succeeds because the transport connects to the validated address, and the
    Host header still carries the logical hostname.
    """
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW", f"rebind.example.com:{local_server}")
    monkeypatch.setattr(
        egress, "_resolve_ips", lambda h: [ipaddress.ip_address("127.0.0.1")]
    )
    with egress.egress_client(timeout=5) as c:
        r = c.get(f"http://rebind.example.com:{local_server}/x")
    assert r.status_code == 200
    assert r.text == f"rebind.example.com:{local_server}"
    assert str(r.request.url).startswith("http://rebind.example.com")


def test_every_redirect_hop_is_rechecked(monkeypatch, local_server):
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW", f"127.0.0.1:{local_server}")
    with egress.egress_client(timeout=5, follow_redirects=True) as c:
        with pytest.raises(egress.HttpEgressError, match="metadata"):
            c.get(f"http://127.0.0.1:{local_server}/redirect-metadata")


def test_http_request_node_blocks_loopback(monkeypatch):
    monkeypatch.delenv("GRAPHYN_HTTP_EGRESS_MODE", raising=False)
    monkeypatch.delenv("GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW", raising=False)
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "PluginPackage/Common/http_request/nodes.py"
    pkg = path.parent
    sys.path.insert(0, str(pkg.parent))
    try:
        mod = importlib.import_module("http_request.nodes")
    finally:
        sys.path.remove(str(pkg.parent))
    node = mod.HttpRequestNode(config={"url": "http://169.254.169.254/latest", "timeout_s": 30})
    with pytest.raises(egress.HttpEgressError, match="metadata"):
        node.process({})


def test_smtp_relay_is_egress_checked(monkeypatch):
    from app.core.notify.smtp_notify import send_email

    monkeypatch.delenv("GRAPHYN_SMTP_DRY_RUN", raising=False)
    with pytest.raises(RuntimeError, match="SMTP egress blocked"):
        send_email(
            to="a@example.com", subject="s", body="b", from_addr="x@example.com",
            credentials={"host": "127.0.0.1", "port": 25, "from_addr": "x@example.com"},
        )


def test_smtp_env_dry_run_forces_preview(monkeypatch):
    from app.core.notify.smtp_notify import send_email

    monkeypatch.setenv("GRAPHYN_SMTP_DRY_RUN", "1")
    receipt = send_email(
        to="a@example.com", subject="s", body="b", from_addr="x@example.com", dry_run=False,
        credentials={"host": "smtp.example.com", "port": 587, "from_addr": "x@example.com",
                     "dry_run": False},
    )
    assert receipt["dry_run"] is True
