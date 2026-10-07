# app/core/distributed/enrollment.py
"""
Bounded Context:  BC5 — Execution Runtime (Mode B worker enrollment)
Responsibility:   Swarm-style worker join: an operator mints a join token, a
                  worker host redeems it once; the control plane assigns the
                  worker_id, issues a short-lived worker credential, signs the
                  worker's CSR with the control CA, pre-registers the worker
                  with the token's pool / labels / plugin ACL and records the
                  enrollment (join token → creator → worker → credential →
                  cert fingerprint) for audit lineage. Also rotation and
                  revocation.
Owns:             join_worker(), rotate_worker_credential(), revoke_worker(),
                  enforce_enrollment(), new_worker_id(), WORKER_CREDENTIAL_TTL.
Public Surface:   Functions above (called by app/api/routers/workers.py and
                  the CLI).
Must NOT:         Import app.api / app.domain; return token secrets except the
                  one-time join/rotate response.
Dependencies:     app.core.trust.users, app.core.distributed.{mtls,registry,
                  queue,models}, stdlib (re, secrets, time).
Reason To Change: Join protocol, credential lifetime, or enrollment policy.
"""
from __future__ import annotations

import logging
import re
import secrets
import time
from typing import Any

from app.core.distributed.models import WorkerInfo
from app.core.trust.users import WORKER_CREDENTIAL_TTL_S, UserStoreError, get_user_store

log = logging.getLogger(__name__)

WORKER_CREDENTIAL_TTL = WORKER_CREDENTIAL_TTL_S
_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class EnrollmentError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def new_worker_id(pool: str | None, requested: str | None = None) -> str:
    """``<name|pool|worker>-<6 hex>``; the suffix keeps ids unguessable and unique."""
    from app.core.distributed.registry import get_worker_registry

    base = _NAME_RE.sub("-", str(requested or pool or "worker")).strip("-.")[:32] or "worker"
    store = get_user_store()
    for _ in range(16):
        wid = f"{base}-{secrets.token_hex(3)}"
        if store.get_enrollment(wid) is None and get_worker_registry().get(wid) is None:
            return wid
    raise EnrollmentError("could not allocate a worker id", 500)


def _sign(csr_pem: str | None, worker_id: str) -> dict[str, Any] | None:
    if not csr_pem:
        return None
    from app.core.distributed.mtls import csr_signing_available, sign_worker_csr

    if not csr_signing_available():
        return None
    try:
        return sign_worker_csr(csr_pem, worker_id)
    except ValueError as exc:
        raise EnrollmentError(str(exc), 400) from exc


def _cert_response(signed: dict[str, Any] | None, csr_given: bool) -> dict[str, Any]:
    from app.core.distributed.mtls import ca_cert_pem

    if signed:
        return {
            "cert_pem": signed["cert_pem"],
            "ca_pem": ca_cert_pem(),
            "cert_fingerprint": signed["fingerprint_sha256"],
            "cert_expires_at": signed["not_after"],
            "cert_status": "issued",
        }
    return {"cert_pem": None, "ca_pem": ca_cert_pem(), "cert_status": "unavailable" if csr_given else "not_requested"}


def join_worker(
    join_token: str,
    *,
    name: str | None = None,
    hostname: str = "",
    csr_pem: str | None = None,
) -> dict[str, Any]:
    """Redeem ``join_token``; returns the one-time worker credential + cert."""
    from app.core.distributed.registry import get_worker_registry

    store = get_user_store()
    parsed_jt = None
    try:
        from app.core.trust.users import parse_token

        parsed = parse_token(join_token)
        if parsed and parsed[0] == "join":
            parsed_jt = store.get_join_token(parsed[1])
    except Exception:
        parsed_jt = None
    worker_id = new_worker_id(parsed_jt.pool if parsed_jt else None, name)
    try:
        jt = store.consume_join_token(join_token, worker_id)
    except UserStoreError as exc:
        raise EnrollmentError(str(exc), exc.status_code) from exc
    signed = _sign(csr_pem, worker_id)
    token, cred = store.issue_credential(
        "worker",
        worker_id=worker_id,
        name=f"join:{jt.id}",
        ttl_s=WORKER_CREDENTIAL_TTL,
        created_by=jt.created_by,
        meta={
            "join_token_id": jt.id,
            "pool": jt.pool,
            "labels": jt.labels,
            "hostname": str(hostname or "")[:128],
            "cert_fingerprint": signed["fingerprint_sha256"] if signed else None,
        },
    )
    enrollment = store.enroll_worker(
        worker_id,
        jt,
        hostname=hostname,
        cert_fingerprint=signed["fingerprint_sha256"] if signed else None,
        cert_expires_at=signed["not_after"] if signed else None,
    )
    get_worker_registry().register(
        WorkerInfo(
            worker_id=worker_id,
            labels=list(jt.labels),
            pools=[jt.pool] if jt.pool else [],
            allowed_plugins=jt.allowed_plugins,
            trusted=True,
            status="offline",
        )
    )
    return {
        "worker_id": worker_id,
        "token": token,
        "credential_id": cred.id,
        "credential_expires_at": cred.expires_at,
        "pool": jt.pool,
        "labels": list(jt.labels),
        "allowed_plugins": jt.allowed_plugins,
        "join_token_id": jt.id,
        "enrollment": enrollment,
        **_cert_response(signed, bool(csr_pem)),
    }


def rotate_worker_credential(
    worker_id: str, *, current_credential_id: str | None, csr_pem: str | None = None
) -> dict[str, Any]:
    """Issue a fresh credential (+ cert when a CSR is sent) and revoke the old ones."""
    store = get_user_store()
    enrollment = store.get_enrollment(worker_id)
    if enrollment is None:
        raise EnrollmentError(f"Worker {worker_id} was not enrolled via join", 404)
    if not enrollment["active"]:
        raise EnrollmentError(f"Worker {worker_id} is revoked", 403)
    prev = store.get_credential(current_credential_id) if current_credential_id else None
    signed = _sign(csr_pem, worker_id)
    meta = dict(prev.meta) if prev else {"join_token_id": enrollment["join_token_id"]}
    meta["rotated_from"] = current_credential_id
    if signed:
        meta["cert_fingerprint"] = signed["fingerprint_sha256"]
        store.update_enrollment_cert(worker_id, signed["fingerprint_sha256"], signed["not_after"])
    token, cred = store.issue_credential(
        "worker",
        worker_id=worker_id,
        name=(prev.name if prev else f"join:{enrollment['join_token_id']}"),
        ttl_s=WORKER_CREDENTIAL_TTL,
        created_by=f"worker:{worker_id}",
        meta=meta,
    )
    revoked = store.revoke_worker_credentials(worker_id, except_id=cred.id)
    return {
        "worker_id": worker_id,
        "token": token,
        "credential_id": cred.id,
        "credential_expires_at": cred.expires_at,
        "revoked_credentials": revoked,
        **_cert_response(signed, bool(csr_pem)),
    }


def revoke_worker(worker_id: str, *, revoked_by: str | None = None) -> dict[str, Any]:
    """Revoke credentials + cert identity, drop the registry row, requeue its jobs."""
    from app.core.distributed.queue import get_job_queue
    from app.core.distributed.registry import get_worker_registry

    store = get_user_store()
    if store.get_enrollment(worker_id) is None and not store.list_credentials(worker_id=worker_id, include_inactive=True):
        raise EnrollmentError(f"Worker {worker_id} has no enrollment or credentials", 404)
    revoked = store.revoke_enrollment(worker_id, revoked_by=revoked_by)
    released: list[str] = []
    try:
        released = get_job_queue().release_jobs_for_worker(worker_id, keep_job_ids=[])
    except Exception as exc:
        log.warning("revoke_worker: releasing jobs of %s failed: %s", worker_id, exc)
    get_worker_registry().remove(worker_id)
    return {"worker_id": worker_id, "revoked_credentials": revoked, "released_job_ids": released, "revoked_at": time.time()}


def enforce_enrollment(info: WorkerInfo, existing: WorkerInfo | None) -> WorkerInfo:
    """Joined workers cannot move pools or relabel themselves (placement = confidentiality).

    For an enrolled worker, pools / labels are control-owned: the stored
    registry row wins (operator PATCH), else the join token's values. The
    token's plugin ACL is re-applied when the registry row was deleted.
    Non-enrolled workers pass through unchanged.
    """
    enrollment = get_user_store().get_enrollment(info.worker_id)
    if enrollment is None:
        return info
    if not enrollment["active"]:
        raise EnrollmentError(f"Worker {info.worker_id} is revoked", 403)
    if existing is not None:
        updates: dict[str, Any] = {"pools": list(existing.pools), "labels": list(existing.labels)}
    else:
        updates = {
            "pools": [enrollment["pool"]] if enrollment["pool"] else list(info.pools),
            "labels": list(enrollment["labels"]) or list(info.labels),
            "allowed_plugins": enrollment["allowed_plugins"],
            "trusted": True,
        }
    return info.model_copy(update=updates)


__all__ = [
    "EnrollmentError",
    "WORKER_CREDENTIAL_TTL",
    "enforce_enrollment",
    "join_worker",
    "new_worker_id",
    "revoke_worker",
    "rotate_worker_credential",
]
