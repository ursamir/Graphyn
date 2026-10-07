# app/core/distributed/mtls.py
"""
Bounded Context:  BC5 — Execution Runtime (Mode B WAVE-2)
Responsibility:   Lab-grade mutual TLS between workers and the control plane:
                  CA/cert generation, SSL contexts, peercert → worker_id mapping,
                  uvicorn peercert scope patch, env knobs.
Owns:             mtls_enabled(), generate_modeb_mtls_certs(), ssl contexts,
                  worker_id_from_peercert(), install_uvicorn_peercert_patch(),
                  uvicorn_ssl_kwargs(), client_ssl_context().
Public Surface:   Functions above + MTLS env helpers.
Must NOT:         Import app.api / app.domain.
Dependencies:     stdlib (ssl, subprocess, os, pathlib, re), optional cryptography.
Reason To Change: Cert SAN conventions, TLS policy, or compose paths evolve.
"""
from __future__ import annotations

import logging
import os
import re
import ssl
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_ENV_ENABLED = "GRAPHYN_MTLS_ENABLED"
_ENV_CA = "GRAPHYN_MTLS_CA_CERT"
_ENV_CERT = "GRAPHYN_MTLS_CERT"
_ENV_KEY = "GRAPHYN_MTLS_KEY"
_ENV_CLIENT_CERT = "GRAPHYN_MTLS_CLIENT_CERT"
_ENV_CLIENT_KEY = "GRAPHYN_MTLS_CLIENT_KEY"
_ENV_SERVER_NAME = "GRAPHYN_MTLS_SERVER_NAME"

_WORKER_URI_RE = re.compile(
    r"(?:urn:graphyn:worker:|spiffe://graphyn/worker/)([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_CN_RE = re.compile(r"(?:^|,)\s*CN\s*=\s*([^,/]+)", re.IGNORECASE)


def mtls_enabled() -> bool:
    """True when mTLS is turned on via flag or cert paths."""
    flag = (os.environ.get(_ENV_ENABLED) or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    # Auto-enable when both server (or client) material is present.
    if (os.environ.get(_ENV_CERT) or "").strip() and (os.environ.get(_ENV_KEY) or "").strip():
        return True
    if (os.environ.get(_ENV_CLIENT_CERT) or "").strip() and (
        os.environ.get(_ENV_CLIENT_KEY) or ""
    ).strip():
        return True
    return False


def mtls_ca_path() -> str | None:
    p = (os.environ.get(_ENV_CA) or "").strip()
    return p or None


def mtls_server_cert_path() -> str | None:
    p = (os.environ.get(_ENV_CERT) or "").strip()
    return p or None


def mtls_server_key_path() -> str | None:
    p = (os.environ.get(_ENV_KEY) or "").strip()
    return p or None


def mtls_client_cert_path() -> str | None:
    p = (os.environ.get(_ENV_CLIENT_CERT) or "").strip()
    return p or None


def mtls_client_key_path() -> str | None:
    p = (os.environ.get(_ENV_CLIENT_KEY) or "").strip()
    return p or None


def mtls_server_name() -> str:
    return (os.environ.get(_ENV_SERVER_NAME) or "graphyn-api").strip() or "graphyn-api"


def _run_openssl(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["openssl", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"openssl {' '.join(args[:4])}… failed ({proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    return proc


def generate_modeb_mtls_certs(
    outdir: str | Path,
    *,
    worker_ids: list[str] | None = None,
    server_dns: list[str] | None = None,
    days: int = 825,
) -> dict[str, Path]:
    """Generate CA, control server cert, and per-worker client certs via openssl.

    Layout::

        {outdir}/ca/ca.pem, ca.key
        {outdir}/control/cert.pem, key.pem
        {outdir}/workers/{worker_id}/cert.pem, key.pem

    Server SAN includes ``graphyn-api``, ``localhost``, and ``server_dns``.
    Worker certs use CN=``worker_id`` and URI SAN ``urn:graphyn:worker:{id}``.
    """
    root = Path(outdir)
    ca_dir = root / "ca"
    control_dir = root / "control"
    workers_dir = root / "workers"
    ca_dir.mkdir(parents=True, exist_ok=True)
    control_dir.mkdir(parents=True, exist_ok=True)
    workers_dir.mkdir(parents=True, exist_ok=True)

    ca_key = ca_dir / "ca.key"
    ca_pem = ca_dir / "ca.pem"
    if not ca_pem.is_file() or not ca_key.is_file():
        _run_openssl(
            [
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-sha256",
                "-days",
                str(days),
                "-nodes",
                "-keyout",
                str(ca_key),
                "-out",
                str(ca_pem),
                "-subj",
                "/O=Graphyn/CN=Graphyn Mode B CA",
            ]
        )
        try:
            os.chmod(ca_key, 0o600)
        except OSError:
            pass

    dns_names = list(server_dns or [])
    for name in ("graphyn-api", "localhost", "127.0.0.1"):
        if name not in dns_names:
            dns_names.append(name)
    san_lines = []
    for i, name in enumerate(dns_names, start=1):
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", name) or ":" in name:
            san_lines.append(f"IP.{i} = {name}")
        else:
            san_lines.append(f"DNS.{i} = {name}")
    # Re-number cleanly
    san_dns: list[str] = []
    san_ip: list[str] = []
    for name in dns_names:
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", name):
            san_ip.append(name)
        else:
            san_dns.append(name)
    san_parts = [f"DNS:{n}" for n in san_dns] + [f"IP:{n}" for n in san_ip]
    san_str = ",".join(san_parts)

    control_key = control_dir / "key.pem"
    control_csr = control_dir / "csr.pem"
    control_cert = control_dir / "cert.pem"
    ext_file = control_dir / "server.ext"
    ext_file.write_text(
        "[v3_req]\n"
        "basicConstraints=CA:FALSE\n"
        "keyUsage=digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        f"subjectAltName={san_str}\n",
        encoding="utf-8",
    )
    _run_openssl(
        [
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(control_key),
            "-out",
            str(control_csr),
            "-subj",
            "/O=Graphyn/CN=graphyn-api",
        ]
    )
    _run_openssl(
        [
            "x509",
            "-req",
            "-in",
            str(control_csr),
            "-CA",
            str(ca_pem),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(control_cert),
            "-days",
            str(days),
            "-sha256",
            "-extfile",
            str(ext_file),
            "-extensions",
            "v3_req",
        ]
    )
    try:
        os.chmod(control_key, 0o600)
    except OSError:
        pass
    control_csr.unlink(missing_ok=True)

    paths: dict[str, Path] = {
        "ca_cert": ca_pem,
        "ca_key": ca_key,
        "control_cert": control_cert,
        "control_key": control_key,
    }

    for wid in worker_ids or ["worker-1"]:
        wid = str(wid).strip()
        if not wid or not re.match(r"^[A-Za-z0-9_.-]+$", wid):
            raise ValueError(f"invalid worker_id for cert: {wid!r}")
        wdir = workers_dir / wid
        wdir.mkdir(parents=True, exist_ok=True)
        wkey = wdir / "key.pem"
        wcsr = wdir / "csr.pem"
        wcert = wdir / "cert.pem"
        wext = wdir / "client.ext"
        wext.write_text(
            "[v3_req]\n"
            "basicConstraints=CA:FALSE\n"
            "keyUsage=digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=clientAuth\n"
            f"subjectAltName=URI:urn:graphyn:worker:{wid},DNS:{wid}\n",
            encoding="utf-8",
        )
        _run_openssl(
            [
                "req",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(wkey),
                "-out",
                str(wcsr),
                "-subj",
                f"/O=Graphyn/CN={wid}",
            ]
        )
        _run_openssl(
            [
                "x509",
                "-req",
                "-in",
                str(wcsr),
                "-CA",
                str(ca_pem),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(wcert),
                "-days",
                str(days),
                "-sha256",
                "-extfile",
                str(wext),
                "-extensions",
                "v3_req",
            ]
        )
        try:
            os.chmod(wkey, 0o600)
        except OSError:
            pass
        wcsr.unlink(missing_ok=True)
        paths[f"worker:{wid}:cert"] = wcert
        paths[f"worker:{wid}:key"] = wkey

    return paths


def worker_id_from_peercert(peercert: dict[str, Any] | None) -> str | None:
    """Extract worker_id from an SSL peercert dict (CN or URI SAN)."""
    if not peercert or not isinstance(peercert, dict):
        return None
    # subjectAltName: (('URI', 'urn:graphyn:worker:s99-ml'), ('DNS', 's99-ml'), ...)
    sans = peercert.get("subjectAltName") or ()
    for entry in sans:
        if not isinstance(entry, (tuple, list)) or len(entry) < 2:
            continue
        kind, value = str(entry[0]), str(entry[1])
        if kind.upper() == "URI":
            m = _WORKER_URI_RE.search(value)
            if m:
                return m.group(1)
    # subject: ((('countryName', 'US'),), (('commonName', 's99-ml'),), ...)
    subject = peercert.get("subject") or ()
    for rdn in subject:
        if not isinstance(rdn, (tuple, list)):
            continue
        for attr in rdn:
            if not isinstance(attr, (tuple, list)) or len(attr) < 2:
                continue
            if str(attr[0]).lower() in ("commonname", "cn"):
                cn = str(attr[1]).strip()
                if cn and re.match(r"^[A-Za-z0-9_.-]+$", cn):
                    return cn
    return None


def worker_id_from_pem(cert_pem: bytes | str) -> str | None:
    """Parse worker_id from a PEM certificate (openssl text or ssl module)."""
    if isinstance(cert_pem, str):
        cert_pem = cert_pem.encode("utf-8")
    try:
        der = ssl.PEM_cert_to_DER_cert(cert_pem.decode("utf-8") if isinstance(cert_pem, bytes) else cert_pem)
    except Exception:
        # Fall back to openssl x509 -noout -text
        try:
            proc = subprocess.run(
                ["openssl", "x509", "-noout", "-subject", "-ext", "subjectAltName"],
                input=cert_pem,
                capture_output=True,
                check=True,
            )
            text = (proc.stdout or b"").decode("utf-8", errors="replace")
            m = _WORKER_URI_RE.search(text)
            if m:
                return m.group(1)
            m2 = _CN_RE.search(text.replace("subject=", ""))
            if m2:
                cn = m2.group(1).strip()
                if re.match(r"^[A-Za-z0-9_.-]+$", cn):
                    return cn
        except Exception as exc:
            log.debug("worker_id_from_pem openssl fallback failed: %s", exc)
        return None
    try:
        # Load via temporary SSL context to get decoded dict — use
        # cryptography-free path: openssl asn1 parse of subject.
        proc = subprocess.run(
            ["openssl", "x509", "-inform", "DER", "-noout", "-subject", "-ext", "subjectAltName"],
            input=der,
            capture_output=True,
            check=True,
        )
        text = (proc.stdout or b"").decode("utf-8", errors="replace")
        m = _WORKER_URI_RE.search(text)
        if m:
            return m.group(1)
        m2 = _CN_RE.search(text)
        if m2:
            cn = m2.group(1).strip()
            if re.match(r"^[A-Za-z0-9_.-]+$", cn):
                return cn
    except Exception as exc:
        log.debug("worker_id_from_pem DER parse failed: %s", exc)
    return None


def server_ssl_context(
    *,
    certfile: str | None = None,
    keyfile: str | None = None,
    ca_certs: str | None = None,
    require_client_cert: bool = True,
) -> ssl.SSLContext:
    """Build a server SSLContext (fail closed when require_client_cert)."""
    certfile = certfile or mtls_server_cert_path()
    keyfile = keyfile or mtls_server_key_path()
    ca_certs = ca_certs or mtls_ca_path()
    if not certfile or not keyfile:
        raise ValueError("GRAPHYN_MTLS_CERT and GRAPHYN_MTLS_KEY are required for server TLS")
    if require_client_cert and not ca_certs:
        raise ValueError("GRAPHYN_MTLS_CA_CERT is required when client certs are required")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
    if ca_certs:
        ctx.load_verify_locations(cafile=ca_certs)
    if require_client_cert:
        ctx.verify_mode = ssl.CERT_REQUIRED
    else:
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def client_ssl_context(
    *,
    certfile: str | None = None,
    keyfile: str | None = None,
    ca_certs: str | None = None,
    check_hostname: bool = True,
) -> ssl.SSLContext:
    """Build a client SSLContext that presents a worker cert and trusts the CA."""
    certfile = certfile or mtls_client_cert_path()
    keyfile = keyfile or mtls_client_key_path()
    ca_certs = ca_certs or mtls_ca_path()
    if not ca_certs:
        raise ValueError("GRAPHYN_MTLS_CA_CERT is required for mTLS client")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_verify_locations(cafile=ca_certs)
    ctx.check_hostname = check_hostname
    ctx.verify_mode = ssl.CERT_REQUIRED
    if certfile and keyfile:
        ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
    elif mtls_enabled():
        raise ValueError(
            "GRAPHYN_MTLS_CLIENT_CERT and GRAPHYN_MTLS_CLIENT_KEY are required "
            "when mTLS is enabled"
        )
    return ctx


def urllib_ssl_context() -> ssl.SSLContext | None:
    """SSL context for worker urllib calls, or None when mTLS is disabled."""
    if not mtls_enabled():
        return None
    # Workers talk to graphyn-api by IP/hostname; allow CN/SAN match via server_name.
    return client_ssl_context(check_hostname=True)


def uvicorn_ssl_kwargs() -> dict[str, Any]:
    """Kwargs for ``uvicorn.run`` / ``Config`` when mTLS is enabled; else ``{}``."""
    if not mtls_enabled():
        return {}
    cert = mtls_server_cert_path()
    key = mtls_server_key_path()
    ca = mtls_ca_path()
    if not cert or not key or not ca:
        raise ValueError(
            "mTLS enabled but GRAPHYN_MTLS_CERT / GRAPHYN_MTLS_KEY / "
            "GRAPHYN_MTLS_CA_CERT are not all set"
        )
    return {
        "ssl_certfile": cert,
        "ssl_keyfile": key,
        "ssl_ca_certs": ca,
        "ssl_cert_reqs": ssl.CERT_REQUIRED,
    }


_PEER_PATCHED = False


def install_uvicorn_peercert_patch() -> None:
    """Inject ``scope['extensions']['peercert']`` from the TLS transport.

    Safe to call multiple times. No-op when uvicorn is not installed.
    """
    global _PEER_PATCHED
    if _PEER_PATCHED:
        return
    try:
        from uvicorn.protocols.http.h11_impl import RequestResponseCycle
    except Exception as exc:
        log.debug("uvicorn peercert patch skipped: %s", exc)
        return

    _orig_init = RequestResponseCycle.__init__

    def _init(self, scope, *args, **kwargs):  # type: ignore[no-untyped-def]
        transport = kwargs.get("transport")
        if transport is None and len(args) >= 2:
            # positional: scope, conn, transport, ...
            transport = args[1]
        if transport is not None and isinstance(scope, dict):
            try:
                peercert = transport.get_extra_info("peercert")
            except Exception:
                peercert = None
            if peercert:
                ext = dict(scope.get("extensions") or {})
                ext["peercert"] = peercert
                scope["extensions"] = ext
        return _orig_init(self, scope, *args, **kwargs)

    RequestResponseCycle.__init__ = _init  # type: ignore[method-assign]
    _PEER_PATCHED = True
    log.info("uvicorn peercert → scope['extensions']['peercert'] patch installed")


def peercert_from_scope(scope: dict[str, Any] | None) -> dict[str, Any] | None:
    if not scope:
        return None
    ext = scope.get("extensions") or {}
    cert = ext.get("peercert")
    return cert if isinstance(cert, dict) else None
