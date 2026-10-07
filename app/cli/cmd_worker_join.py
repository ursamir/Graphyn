# app/cli/cmd_worker_join.py
"""
Bounded Context:  CLI Interface
Responsibility:   ``graphyn worker join`` (Swarm-style enrollment) and the
                  worker-side enrollment file: generate key + CSR, redeem a
                  join token, persist the control-assigned worker id,
                  credential and client cert under GRAPHYN_HOME/worker/, and
                  rotate the credential before it expires.
Owns:             cmd_worker_join, load_enrollment, save_enrollment,
                  apply_enrollment_mtls_env, rotate_if_due, enrollment_dir.
Public Surface:   Functions above (used by cmd_worker.cmd_worker_start).
Must NOT:         Import app.api; print the credential secret.
Dependencies:     stdlib (json, os, socket, subprocess, time, urllib),
                  app.core.config.graphyn_home, openssl binary (CSR).
Reason To Change: Join protocol or enrollment file layout changes.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_FILE = "enrollment.json"


def enrollment_dir() -> Path:
    override = (os.environ.get("GRAPHYN_WORKER_ENROLLMENT_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    from app.core.config import graphyn_home

    return graphyn_home() / "worker"


def load_enrollment() -> dict[str, Any] | None:
    p = enrollment_dir() / _FILE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def save_enrollment(state: dict[str, Any]) -> Path:
    d = enrollment_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    if state.get("cert_pem"):
        _write_private(d / "cert.pem", state.pop("cert_pem"))
        state["cert_path"] = str(d / "cert.pem")
    if state.get("ca_pem"):
        _write_private(d / "ca.pem", state.pop("ca_pem"))
        state["ca_path"] = str(d / "ca.pem")
    state.pop("cert_pem", None)
    state.pop("ca_pem", None)
    _write_private(d / _FILE, json.dumps(state, indent=2, sort_keys=True))
    return d / _FILE


def _make_csr(key_path: Path, *, new_key: bool) -> str:
    if new_key or not key_path.is_file():
        key_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(key_path)],
            check=True,
            capture_output=True,
        )
        os.chmod(key_path, 0o600)
    proc = subprocess.run(
        ["openssl", "req", "-new", "-key", str(key_path), "-subj", "/O=Graphyn/CN=pending-join"],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def _post(url: str, payload: dict, *, token: str | None = None, ctx=None) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    kw = {"context": ctx} if ctx is not None else {}
    try:
        with urllib.request.urlopen(req, timeout=30, **kw) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def cmd_worker_join(args) -> None:
    control_url = (args.control_url or os.environ.get("GRAPHYN_CONTROL_URL") or "").rstrip("/")
    token = (args.token or os.environ.get("GRAPHYN_JOIN_TOKEN") or "").strip()
    if not control_url or not token:
        print("error: --control-url and --token (or GRAPHYN_JOIN_TOKEN) are required", file=sys.stderr)
        sys.exit(2)
    existing = load_enrollment()
    if existing and not args.force:
        print(
            f"error: this host is already enrolled as {existing.get('worker_id')} "
            f"({enrollment_dir()}); pass --force to join again",
            file=sys.stderr,
        )
        sys.exit(1)
    d = enrollment_dir()
    csr = None if args.no_cert else _make_csr(d / "key.pem", new_key=True)
    ctx = None
    if args.ca_cert:
        import ssl

        ctx = ssl.create_default_context(cafile=args.ca_cert)
    try:
        out = _post(
            f"{control_url}/workers/join",
            {"token": token, "name": args.name, "hostname": socket.gethostname(), "csr_pem": csr},
            ctx=ctx,
        )
    except Exception as exc:
        print(f"error: join failed: {exc}", file=sys.stderr)
        sys.exit(1)
    state = {
        "worker_id": out["worker_id"],
        "token": out["token"],
        "credential_id": out["credential_id"],
        "credential_expires_at": out.get("credential_expires_at"),
        "control_url": (args.worker_control_url or control_url).rstrip("/"),
        "pool": out.get("pool"),
        "labels": out.get("labels") or [],
        "join_token_id": out.get("join_token_id"),
        "cert_status": out.get("cert_status"),
        "cert_fingerprint": out.get("cert_fingerprint"),
        "key_path": str(d / "key.pem") if csr else None,
        "cert_pem": out.get("cert_pem"),
        "ca_pem": out.get("ca_pem"),
        "joined_at": time.time(),
    }
    path = save_enrollment(state)
    print(f"Joined as {state['worker_id']} (pool={state['pool'] or '-'}, labels={','.join(state['labels']) or '-'})")
    print(f"  credential {state['credential_id']} saved to {path}")
    if state.get("cert_path"):
        print(f"  client cert {state['cert_fingerprint'][:16]}… saved (mTLS ready)")
    elif csr:
        print("  control has no CA key configured — no client cert issued (bearer credential only)")
    print("Start with: graphyn worker start")


def apply_enrollment_mtls_env(state: dict[str, Any], control_url: str) -> None:
    """Point GRAPHYN_MTLS_* at the joined cert when talking HTTPS and nothing else is set."""
    if not control_url.startswith("https://") or not state.get("cert_path") or not state.get("key_path"):
        return
    if (os.environ.get("GRAPHYN_MTLS_CLIENT_CERT") or "").strip():
        return
    os.environ["GRAPHYN_MTLS_CLIENT_CERT"] = state["cert_path"]
    os.environ["GRAPHYN_MTLS_CLIENT_KEY"] = state["key_path"]
    if state.get("ca_path") and not (os.environ.get("GRAPHYN_MTLS_CA_CERT") or "").strip():
        os.environ["GRAPHYN_MTLS_CA_CERT"] = state["ca_path"]
    os.environ.setdefault("GRAPHYN_MTLS_ENABLED", "1")


def rotation_due(state: dict[str, Any], *, now: float | None = None) -> bool:
    """Rotate once less than a third of the credential lifetime remains."""
    exp = state.get("credential_expires_at")
    if not exp:
        return False
    from app.core.distributed.enrollment import WORKER_CREDENTIAL_TTL

    return float(exp) - (now or time.time()) < WORKER_CREDENTIAL_TTL / 3


def rotate_if_due(state: dict[str, Any], control_url: str, *, ssl_ctx=None, force: bool = False) -> dict[str, Any] | None:
    """Rotate the saved credential (+ cert); returns the new state or None."""
    if not force and not rotation_due(state):
        return None
    csr = None
    if state.get("key_path"):
        csr = _make_csr(Path(state["key_path"]), new_key=False)
    out = _post(
        f"{control_url}/workers/{state['worker_id']}/credentials/rotate",
        {"csr_pem": csr},
        token=state["token"],
        ctx=ssl_ctx,
    )
    new = dict(state)
    new.update(
        token=out["token"],
        credential_id=out["credential_id"],
        credential_expires_at=out.get("credential_expires_at"),
        rotated_at=time.time(),
    )
    if out.get("cert_pem"):
        new["cert_pem"] = out["cert_pem"]
        new["cert_fingerprint"] = out.get("cert_fingerprint")
    if out.get("ca_pem"):
        new["ca_pem"] = out["ca_pem"]
    save_enrollment(new)
    return load_enrollment()


def add_worker_join_parser(worker_sub) -> None:
    p = worker_sub.add_parser(
        "join",
        help="Enroll this host with a control plane using a join token",
        description=(
            "Redeem a one-time join token (minted in the console or via POST /workers/join-tokens). "
            "The control plane assigns the worker id, pool and labels and returns a worker "
            "credential (+ CA-signed client cert). Saved under $GRAPHYN_HOME/worker/."
        ),
    )
    p.add_argument("--control-url", default=os.environ.get("GRAPHYN_CONTROL_URL"), metavar="URL",
                   help="Control API used for the join call, e.g. http://control:8001/api/v1")
    p.add_argument("--token", default=None, help="Join token gxj_… (or GRAPHYN_JOIN_TOKEN)")
    p.add_argument("--name", default=None, help="Preferred worker id prefix (control appends a suffix)")
    p.add_argument("--worker-control-url", default=None, metavar="URL",
                   help="Control URL for job traffic if it differs (e.g. the https mTLS listener)")
    p.add_argument("--ca-cert", default=None, help="CA bundle to verify an https control URL during join")
    p.add_argument("--no-cert", action="store_true", help="Do not request a client certificate")
    p.add_argument("--force", action="store_true", help="Replace an existing enrollment on this host")
    p.set_defaults(func=cmd_worker_join)


__all__ = [
    "add_worker_join_parser",
    "apply_enrollment_mtls_env",
    "cmd_worker_join",
    "enrollment_dir",
    "load_enrollment",
    "rotate_if_due",
    "rotation_due",
    "save_enrollment",
]
