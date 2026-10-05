# app/core/pipelines/hooks.py
"""
Bounded Context:  BC6 — Observability & Storage / ops (workflow triggers)
Responsibility:   Inbound webhook triggers for saved project pipelines: hook
                  settings per pipeline, HMAC signature verification with
                  replay protection, per-hook rate limiting, Idempotency-Key
                  dedupe, header filtering, and starting the run with the
                  payload injected into the graph's ``webhook_trigger`` nodes.
Owns:             HookError, hook settings CRUD (get_hook / put_hook /
                  delete_hook / rotate_hook_secret / public_hook_view),
                  sign_payload(), verify_signature(), remember_signature(),
                  check_rate_limit(),
                  filter_headers(), start_webhook_run().
Public Surface:   The functions above + WEBHOOK_TRIGGER_NODE_TYPE,
                  SIGNATURE_HEADER, TIMESTAMP_HEADER, max_body_bytes().
Must NOT:         Import app.api / app.domain; log secrets or payload bodies.
Dependencies:     stdlib (hashlib, hmac, json, threading, time, uuid);
                  app.core.credentials (inbound_webhook secret), pipeline
                  environments / project_pipelines, graph_prepare,
                  run_inputs, run_journal, trust.audit, runtime_backend (lazy).
Reason To Change: Signature scheme, hook settings schema, or trigger policy change.

Signature scheme (Stripe-style, timestamp bound into the MAC):

    X-Graphyn-Timestamp: <unix seconds>
    X-Graphyn-Signature: sha256=<hex HMAC-SHA256(secret, "<timestamp>." + raw_body)>

The timestamp must be within ±``GRAPHYN_WEBHOOK_TOLERANCE_S`` (default 300 s)
of server time, and a signature already accepted inside that window is
rejected as a replay (in-process cache).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets as _secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

WEBHOOK_TRIGGER_NODE_TYPE = "webhook_trigger"
SIGNATURE_HEADER = "x-graphyn-signature"
TIMESTAMP_HEADER = "x-graphyn-timestamp"
HOOK_FILE = "hook.json"
IDEMPOTENCY_FILE = "hook_idempotency.json"
IDEMPOTENCY_TTL_S = 24 * 3600
ENV_NAMES = ("draft", "staging", "prod")

# Headers forwarded to the webhook_trigger node (lower-case). Credentials
# (authorization, cookie, signature) are never forwarded.
DEFAULT_HEADER_ALLOWLIST = frozenset({
    "content-type",
    "user-agent",
    "x-request-id",
    "x-github-event",
    "x-github-delivery",
    "x-gitlab-event",
    "x-event-type",
    "x-graphyn-timestamp",
    "idempotency-key",
})
_NEVER_FORWARD = frozenset({"authorization", "cookie", "proxy-authorization", SIGNATURE_HEADER})


class HookError(Exception):
    """Hook request refused. ``status_code`` maps directly to HTTP."""

    def __init__(self, status_code: int, code: str, message: str, *, headers: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}


# ── Settings storage ───────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bundle_dir(project_dir: Path, pipeline: str) -> Path:
    from app.core.pipelines.project_pipelines import SAFE_PIPELINE_NAME_RE, pipelines_dir

    if not SAFE_PIPELINE_NAME_RE.match(pipeline or "") or len(pipeline) > 128:
        raise HookError(422, "validation_failed", f"Invalid pipeline name {pipeline!r}")
    return pipelines_dir(Path(project_dir)) / pipeline


def _pipeline_exists(project_dir: Path, pipeline: str) -> bool:
    from app.core.pipelines.project_pipelines import pipelines_dir

    return (pipelines_dir(Path(project_dir)) / f"{pipeline}.graph.json").is_file()


def hook_path(project_dir: Path, pipeline: str) -> Path:
    return _bundle_dir(project_dir, pipeline) / HOOK_FILE


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


_SETTINGS_LOCK = threading.RLock()


def get_hook(project_dir: Path, pipeline: str) -> dict[str, Any] | None:
    """Stored hook settings, or None when the pipeline has no hook."""
    path = hook_path(project_dir, pipeline)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise HookError(500, "hook_corrupt", f"hook.json for {pipeline!r} is unreadable: {exc}") from exc
    return data if isinstance(data, dict) else None


def _clean_env(env: Any, default: str = "prod") -> str:
    text = str(env or default).strip().lower()
    if text not in ENV_NAMES:
        raise HookError(422, "validation_failed", "env must be draft, staging, or prod")
    return text


def _clean_header_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HookError(422, "validation_failed", "header_allowlist must be an array of header names")
    out: list[str] = []
    for item in raw[:50]:
        name = str(item or "").strip().lower()
        if not name or len(name) > 64 or name in _NEVER_FORWARD:
            continue
        if all(c.isalnum() or c in "-_" for c in name) and name not in out:
            out.append(name)
    return out


def put_hook(
    project_dir: Path,
    pipeline: str,
    *,
    enabled: bool | None = None,
    env: str | None = None,
    allowed_envs: list[str] | None = None,
    header_allowlist: list[str] | None = None,
    actor: str = "unknown",
) -> dict[str, Any]:
    """Create or update hook settings (secret untouched; see rotate)."""
    if not _pipeline_exists(project_dir, pipeline):
        raise HookError(404, "not_found", f"Pipeline '{pipeline}' not found")
    with _SETTINGS_LOCK:
        current = get_hook(project_dir, pipeline) or {}
        now = _now_iso()
        hook = dict(current)
        if not hook:
            hook = {
                "hook_id": uuid.uuid4().hex[:16],
                "enabled": False,
                "env": "prod",
                "allowed_envs": None,
                "header_allowlist": [],
                "secret_connection_id": None,
                "created_by": actor,
                "created_at": now,
                "rotated_at": None,
            }
        if enabled is not None:
            hook["enabled"] = bool(enabled)
        if env is not None:
            hook["env"] = _clean_env(env)
        if allowed_envs is not None:
            if not isinstance(allowed_envs, list):
                raise HookError(422, "validation_failed", "allowed_envs must be an array")
            hook["allowed_envs"] = sorted({_clean_env(e) for e in allowed_envs}) or None
        if header_allowlist is not None:
            hook["header_allowlist"] = _clean_header_list(header_allowlist)
        hook["updated_at"] = now
        hook["updated_by"] = actor
        _atomic_write(hook_path(project_dir, pipeline), hook)
        return hook


def rotate_hook_secret(project_dir: Path, pipeline: str, *, actor: str = "unknown") -> tuple[dict[str, Any], str]:
    """Create (or rotate) the hook's signing secret. Returns ``(hook, secret)``.

    The secret lives only in the encrypted credentials store (kind
    ``inbound_webhook``); the hook stores the connection id. The plaintext is
    returned once to the caller and never persisted elsewhere.
    """
    from app.core.credentials import create_connection, update_connection
    from app.core.credentials.errors import CredentialNotFoundError
    from app.core.credentials.inbound_webhook import INBOUND_WEBHOOK_KIND, ensure_inbound_webhook_kind

    ensure_inbound_webhook_kind()
    hook = get_hook(project_dir, pipeline) or put_hook(project_dir, pipeline, actor=actor)
    secret = "whsec_" + _secrets.token_urlsafe(32)
    workspace = Path(project_dir).name
    payload = {"secret": secret, "workspace": workspace, "pipeline": pipeline}
    with _SETTINGS_LOCK:
        cid = hook.get("secret_connection_id")
        rotated = False
        if cid:
            try:
                update_connection(str(cid), payload=payload, rotate=True)
                rotated = True
            except CredentialNotFoundError:
                cid = None
        if not cid:
            meta = create_connection(
                name=f"hook:{workspace}/{pipeline}",
                kind=INBOUND_WEBHOOK_KIND,
                payload=payload,
                meta={"workspace": workspace, "pipeline": pipeline, "hook_id": hook.get("hook_id")},
            )
            cid = meta["id"]
        hook = dict(get_hook(project_dir, pipeline) or hook)
        hook["secret_connection_id"] = cid
        hook["rotated_at"] = _now_iso()
        hook["rotated_by"] = actor
        hook["secret_rotations"] = int(hook.get("secret_rotations") or 0) + (1 if rotated else 0)
        _atomic_write(hook_path(project_dir, pipeline), hook)
    return hook, secret


def delete_hook(project_dir: Path, pipeline: str) -> dict[str, Any] | None:
    """Remove hook settings and revoke its secret connection. Returns the old hook."""
    with _SETTINGS_LOCK:
        hook = get_hook(project_dir, pipeline)
        if hook is None:
            return None
        cid = hook.get("secret_connection_id")
        if cid:
            try:
                from app.core.credentials import revoke_connection

                revoke_connection(str(cid), delete=True)
            except Exception:
                log.warning("hooks: could not delete secret connection %s", cid)
        try:
            hook_path(project_dir, pipeline).unlink()
        except FileNotFoundError:
            pass
        try:
            (_bundle_dir(project_dir, pipeline) / IDEMPOTENCY_FILE).unlink()
        except FileNotFoundError:
            pass
        return hook


def hook_url_path(workspace: str, pipeline: str) -> str:
    return f"/api/v1/hooks/{workspace}/{pipeline}"


def public_hook_view(hook: dict[str, Any] | None, workspace: str, pipeline: str) -> dict[str, Any]:
    """API view of hook settings (never contains the secret)."""
    h = hook or {}
    env = h.get("env") or "prod"
    return {
        "workspace": workspace,
        "pipeline": pipeline,
        "exists": hook is not None,
        "hook_id": h.get("hook_id"),
        "enabled": bool(h.get("enabled")),
        "env": env,
        "allowed_envs": list(h.get("allowed_envs") or [env]),
        "header_allowlist": list(h.get("header_allowlist") or []),
        "url_path": hook_url_path(workspace, pipeline),
        "secret_connection_id": h.get("secret_connection_id"),
        "has_secret": bool(h.get("secret_connection_id")),
        "created_by": h.get("created_by"),
        "created_at": h.get("created_at"),
        "updated_at": h.get("updated_at"),
        "rotated_at": h.get("rotated_at"),
        "signature_header": "X-Graphyn-Signature",
        "timestamp_header": "X-Graphyn-Timestamp",
        "signature_scheme": "sha256=HMAC_SHA256(secret, '<timestamp>.' + raw_body)",
    }


# ── Limits ─────────────────────────────────────────────────────────────────────

def _env_int(name: str, default: int, lo: int = 1) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        return max(lo, int(raw)) if raw else default
    except ValueError:
        return default


def max_body_bytes() -> int:
    """``GRAPHYN_WEBHOOK_MAX_BYTES`` (default 1 MiB)."""
    return _env_int("GRAPHYN_WEBHOOK_MAX_BYTES", 1024 * 1024)


def tolerance_s() -> int:
    return _env_int("GRAPHYN_WEBHOOK_TOLERANCE_S", 300)


# ── Signature ──────────────────────────────────────────────────────────────────

def sign_payload(secret: str, timestamp: str | int, raw_body: bytes) -> str:
    """Return ``sha256=<hex>`` for ``"<timestamp>." + raw_body``."""
    msg = str(timestamp).encode("ascii") + b"." + (raw_body or b"")
    digest = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


_REPLAY_LOCK = threading.Lock()
_SEEN_SIGNATURES: dict[str, float] = {}


def _remember_signature(sig: str, now: float, window: int) -> bool:
    """True when ``sig`` is new inside the window (and records it)."""
    with _REPLAY_LOCK:
        if len(_SEEN_SIGNATURES) > 10_000:
            for key, exp in list(_SEEN_SIGNATURES.items()):
                if exp < now:
                    _SEEN_SIGNATURES.pop(key, None)
        exp = _SEEN_SIGNATURES.get(sig)
        if exp is not None and exp >= now:
            return False
        _SEEN_SIGNATURES[sig] = now + 2 * window
        return True


def verify_signature(
    secret: str,
    raw_body: bytes,
    signature: str | None,
    timestamp: str | None,
    *,
    now: float | None = None,
    window_s: int | None = None,
    check_replay: bool = True,
) -> None:
    """Raise HookError(401) unless the signature + timestamp are valid."""
    window = int(window_s if window_s is not None else tolerance_s())
    current = float(now if now is not None else time.time())
    ts_text = str(timestamp or "").strip()
    if not ts_text.isdigit():
        raise HookError(401, "invalid_signature", "Missing or malformed X-Graphyn-Timestamp")
    if abs(current - int(ts_text)) > window:
        raise HookError(401, "timestamp_out_of_window", f"X-Graphyn-Timestamp outside ±{window}s window")
    sig = str(signature or "").strip()
    if not sig.startswith("sha256="):
        raise HookError(401, "invalid_signature", "X-Graphyn-Signature must be 'sha256=<hex>'")
    expected = sign_payload(secret, ts_text, raw_body)
    if not hmac.compare_digest(expected.encode("ascii"), sig.lower().encode("ascii", "ignore")):
        raise HookError(401, "invalid_signature", "Signature mismatch")
    if check_replay and not _remember_signature(sig.lower(), current, window):
        raise HookError(409, "replay_detected", "This signed request was already accepted")


def remember_signature(signature: str | None, timestamp: str | None = None, *,
                       now: float | None = None, window_s: int | None = None) -> bool:
    """Record an accepted signature; False when it was already seen (replay)."""
    window = int(window_s if window_s is not None else tolerance_s())
    current = float(now if now is not None else time.time())
    return _remember_signature(str(signature or "").strip().lower(), current, window)


def _reset_replay_cache() -> None:
    with _REPLAY_LOCK:
        _SEEN_SIGNATURES.clear()


# ── Rate limit (in-process token bucket per hook) ──────────────────────────────

_BUCKET_LOCK = threading.Lock()
_BUCKETS: dict[str, tuple[float, float]] = {}


def check_rate_limit(hook_id: str, *, now: float | None = None) -> None:
    """Consume one token for ``hook_id`` or raise HookError(429).

    Capacity ``GRAPHYN_WEBHOOK_RATE_BURST`` (default 10), refill
    ``GRAPHYN_WEBHOOK_RATE_PER_MIN`` tokens per minute (default 60).
    """
    burst = float(_env_int("GRAPHYN_WEBHOOK_RATE_BURST", 10))
    per_s = _env_int("GRAPHYN_WEBHOOK_RATE_PER_MIN", 60) / 60.0
    t = float(now if now is not None else time.monotonic())
    with _BUCKET_LOCK:
        tokens, last = _BUCKETS.get(hook_id, (burst, t))
        tokens = min(burst, tokens + max(0.0, t - last) * per_s)
        if tokens < 1.0:
            retry = max(1, int((1.0 - tokens) / per_s) + 1) if per_s > 0 else 60
            _BUCKETS[hook_id] = (tokens, t)
            raise HookError(429, "rate_limited", "Webhook rate limit exceeded",
                            headers={"Retry-After": str(retry)})
        _BUCKETS[hook_id] = (tokens - 1.0, t)


def _reset_rate_limits() -> None:
    with _BUCKET_LOCK:
        _BUCKETS.clear()


# ── Payload helpers ────────────────────────────────────────────────────────────

def filter_headers(headers: dict[str, str], extra_allow: list[str] | None = None) -> dict[str, str]:
    allow = set(DEFAULT_HEADER_ALLOWLIST) | {h.lower() for h in (extra_allow or [])}
    out: dict[str, str] = {}
    for key, value in headers.items():
        k = str(key).lower()
        if k in allow and k not in _NEVER_FORWARD:
            out[k] = str(value)[:1024]
    return out


def parse_body(raw_body: bytes) -> Any:
    if not raw_body or not raw_body.strip():
        return {}
    try:
        return json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HookError(400, "invalid_body", f"Body must be JSON: {exc}") from exc


# ── Idempotency (per hook, 24 h) ───────────────────────────────────────────────

_IDEM_LOCK = threading.Lock()


def _idem_path(project_dir: Path, pipeline: str) -> Path:
    return _bundle_dir(project_dir, pipeline) / IDEMPOTENCY_FILE


def _idem_load(path: Path, now: float) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(v, dict) and float(v.get("at") or 0) + IDEMPOTENCY_TTL_S > now}


def _idem_key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ── Run start ──────────────────────────────────────────────────────────────────

def _spawn(fn: Any, name: str) -> None:
    """Start the run body in a daemon thread (tests replace this)."""
    threading.Thread(target=fn, daemon=True, name=name).start()


def _load_env_graph(project_dir: Path, pipeline: str, env: str) -> Any:
    from app.core.execution.graph_prepare import GraphPrepareError, check_graph_executable, rewire_for_execution
    from app.core.ir.loader import load_ir
    from app.core.pipelines.pipeline_environments import get_environment_graph

    try:
        data = get_environment_graph(Path(project_dir), pipeline, env=env)
    except FileNotFoundError as exc:
        if str(exc).startswith("No version pointed"):
            raise HookError(409, "env_not_published",
                            f"Pipeline {pipeline} has no published {env} version") from exc
        raise HookError(404, "not_found", f"Pipeline '{pipeline}' not found") from exc
    except ValueError as exc:
        raise HookError(422, "validation_failed", str(exc)) from exc
    try:
        graph = rewire_for_execution(load_ir(data))
        check_graph_executable(graph)
    except GraphPrepareError as exc:
        raise HookError(422, "graph_invalid", str(exc)) from exc
    except HookError:
        raise
    except Exception as exc:
        raise HookError(422, "graph_invalid", str(exc)) from exc
    return graph


def find_idempotent_run(project_dir: Path, pipeline: str, idempotency_key: str | None) -> str | None:
    """Run id already started for this Idempotency-Key (within the TTL), else None.

    Checked *before* signature replay detection: a sender retrying a delivery
    re-sends the identical signed request with the same key and must get the
    original run back (200, idempotent_replay), not a 409 replay error.
    """
    key = str(idempotency_key or "").strip()
    if not key or len(key) > 256:
        return None
    with _IDEM_LOCK:
        prior = _idem_load(_idem_path(project_dir, pipeline), time.time()).get(_idem_key_hash(key))
    return str(prior["run_id"]) if prior and prior.get("run_id") else None


def start_webhook_run(
    *,
    project_dir: Path,
    workspace: str,
    pipeline: str,
    hook: dict[str, Any],
    env: str,
    raw_body: bytes,
    headers: dict[str, str],
    query: dict[str, str],
    actor: str,
    actor_verified: bool,
    auth_method: str,
    source_ip: str | None,
    idempotency_key: str | None = None,
    principal: str | None = None,
) -> dict[str, Any]:
    """Validate the payload, start the run asynchronously, return the ack body.

    Ack: ``{run_id, status: "pending", hook_id, env, idempotent_replay}``.
    """
    from app.core.execution.graph_prepare import persist_project_fields, persist_run_identity
    from app.core.execution.run_inputs import persist_run_inputs_meta, prepare_run_inputs

    body = parse_body(raw_body)
    payload_sha = hashlib.sha256(raw_body or b"").hexdigest()
    hook_id = str(hook.get("hook_id") or "")

    idem_hash = None
    if idempotency_key:
        key = str(idempotency_key).strip()
        if not key or len(key) > 256:
            raise HookError(422, "validation_failed", "Idempotency-Key must be 1..256 characters")
        idem_hash = _idem_key_hash(key)

    graph = _load_env_graph(project_dir, pipeline, env)
    trigger_ids = [n.id for n in graph.nodes if n.node_type == WEBHOOK_TRIGGER_NODE_TYPE]
    if not trigger_ids:
        raise HookError(422, "no_webhook_trigger",
                        f"Pipeline '{pipeline}' ({env}) has no {WEBHOOK_TRIGGER_NODE_TYPE} node")
    fwd_headers = filter_headers(headers, hook.get("header_allowlist"))
    event = {"body": body, "headers": fwd_headers, "query": dict(query)}
    raw_inputs = {nid: dict(event) for nid in trigger_ids}
    try:
        overrides, inputs_meta = prepare_run_inputs(graph, raw_inputs, max_bytes=max(max_body_bytes() * 2, 1))
    except ValueError as exc:
        raise HookError(422, "validation_failed", str(exc)) from exc

    from app.core.runs.run_journal import RunManager

    path = _idem_path(project_dir, pipeline)
    with _IDEM_LOCK:
        now = time.time()
        if idem_hash:
            seen = _idem_load(path, now)
            prior = seen.get(idem_hash)
            if prior and prior.get("run_id"):
                return {"run_id": prior["run_id"], "status": "accepted", "hook_id": hook_id,
                        "env": env, "idempotent_replay": True}
        run_mgr = RunManager()
        run_id = run_mgr.run_id
        if idem_hash:
            seen[idem_hash] = {"run_id": run_id, "at": now}
            try:
                _atomic_write(path, seen)
            except OSError:
                log.warning("hooks: could not persist idempotency record for %s", pipeline)

    persist_project_fields(run_mgr, {"project": workspace})
    persist_run_identity(
        run_mgr,
        actor=actor,
        trigger="webhook",
        payload={"pipeline": pipeline, "pipeline_env": env},
        actor_verified=actor_verified,
        claimed_actor=principal,
    )
    persist_run_inputs_meta(run_mgr, inputs_meta)
    from app.core.execution.run_inputs import persist_run_inputs

    persist_run_inputs(run_mgr, overrides)
    webhook_meta = {
        "hook_id": hook_id,
        "auth": auth_method,
        "payload_sha256": payload_sha,
        "payload_bytes": len(raw_body or b""),
        "idempotency_key": idempotency_key or None,
        "source_ip": source_ip,
        "content_type": fwd_headers.get("content-type"),
        "trigger_nodes": trigger_ids,
        "received_at": _now_iso(),
    }
    try:
        run_mgr._write_meta_field("webhook", webhook_meta)
    except Exception:
        log.debug("hooks: could not persist webhook meta", exc_info=True)

    try:
        from app.core.trust.audit import record_audit

        audit_meta = {
            "workspace": workspace, "pipeline": pipeline, "env": env, "run_id": run_id,
            "hook_id": hook_id, "auth": auth_method, "source_ip": source_ip,
            "payload_sha256": payload_sha, "payload_bytes": len(raw_body or b""),
            "idempotency_key": idempotency_key or None,
        }
        record_audit(actor=actor, action="webhook.received", resource_type="pipeline",
                     resource_id=f"{workspace}/{pipeline}", meta=audit_meta,
                     actor_verified=actor_verified, claimed_actor=principal)
        record_audit(actor=actor, action="run.start", resource_type="run", resource_id=run_id,
                     meta={"graph_name": getattr(graph.metadata, "name", None), "mode": "webhook",
                           "trigger": "webhook", "project": workspace, "pipeline": pipeline,
                           "env": env, "hook_id": hook_id, "source_ip": source_ip},
                     actor_verified=actor_verified, claimed_actor=principal)
    except Exception:
        log.debug("hooks: audit failed", exc_info=True)

    def _run() -> None:
        from app.core.execution.runtime_backend import get_backend

        try:
            get_backend().execute(graph, run_manager=run_mgr, input_overrides=overrides)
        except Exception as exc:
            try:
                run_mgr.mark_failed(str(exc))
            except Exception:
                pass

    _spawn(_run, f"graphyn-webhook-{run_id[:8]}")
    return {"run_id": run_id, "status": "pending", "hook_id": hook_id, "env": env,
            "idempotent_replay": False}
