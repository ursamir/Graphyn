# app/api/routers/trace.py
"""
Bounded Context:  REST API Layer
Responsibility:   Unified Trace (backtrack) and thin audit log endpoints.
Owns:             GET /trace, GET /audit (offset / run_id / resource_id / action / q /
                  category / exclude_category filters over the whole log;
                  total + has_more; events carry label + category).
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain storage logic — delegate to app.core.runs.trace / audit.
Dependencies:     fastapi, app.core.runs.trace, app.core.trust.audit,
                  app.api.run_ids (run_id prefix resolution).
Reason To Change: Trace/audit response schema changes or new query modes.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["trace"])


@router.get("/trace", summary="Unified backtrack Trace payload")
def get_trace(
    artifact_id: Optional[str] = Query(None, description="Artifact to backtrack from"),
    run_id: Optional[str] = Query(None, description="Run to backtrack from"),
    node_id: Optional[str] = Query(None, description="Optional node focus within the run"),
):
    """Return artifact → node → run → graph → worker chain.

    Partial payloads are returned when pieces are missing (see ``warnings``).
    """
    if not artifact_id and not run_id:
        raise HTTPException(
            status_code=400,
            detail="Provide artifact_id and/or run_id query parameters",
        )
    from app.core.runs.trace import assemble_trace

    if run_id and run_id.strip():
        from app.api.run_ids import resolve_run_id_http

        # Unique prefix >= 8 → full id; ambiguous → 409 run_id_ambiguous.
        # Unknown ids still return a partial payload (``run_not_found`` warning).
        run_id = resolve_run_id_http(run_id, allow_missing=True)
    try:
        return assemble_trace(artifact_id=artifact_id, run_id=run_id, node_id=node_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/trace/{kind}/{id}", summary="Trace by kind/id path")
def get_trace_by_path(kind: str, id: str, node_id: Optional[str] = Query(None)):
    """Convenience path form: ``/trace/artifact/{id}`` or ``/trace/run/{id}``."""
    kind_norm = kind.strip().lower()
    if kind_norm in ("artifact", "artifacts"):
        return get_trace(artifact_id=id, run_id=None, node_id=node_id)
    if kind_norm in ("run", "runs"):
        return get_trace(artifact_id=None, run_id=id, node_id=node_id)
    raise HTTPException(status_code=400, detail="kind must be 'artifact' or 'run'")


@router.get("/audit", summary="List / search audit events")
def get_audit(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0, description="Skip this many matching events (newest first)"),
    run_id: str | None = Query(None, description="Events of this run (full id or prefix >= 8), incl. replays of it"),
    resource_id: str | None = Query(None, description="Exact resource id (or prefix >= 8)"),
    action: str | None = Query(None, description="Exact action, or 'run.*' prefix"),
    q: str | None = Query(None, description="Case-insensitive free-text search over the event (and its label)"),
    category: str | None = Query(None, description="Only these categories (comma list): run, model, admin, system, ui"),
    exclude_category: str | None = Query(None, description="Hide these categories (comma list), e.g. ui,system"),
    actor: str | None = Query(None, description="Exact actor name (case-insensitive)"),
    user_id: str | None = Query(None, description="Principal user id (u_…)"),
    credential_id: str | None = Query(None, description="Principal credential / token id"),
    worker_id: str | None = Query(None, description="Worker principal / resource / metadata worker_id"),
    since: str | None = Query(None, description="ISO timestamp lower bound (inclusive)"),
    until: str | None = Query(None, description="ISO timestamp upper bound (inclusive)"),
):
    """Newest-first append-only audit events, filtered and paged over the whole log.

    Every event carries read-time ``label`` (plain words, e.g. "Model
    registered") and ``category`` (run | model | admin | system | ui)
    computed from its ``action``; raw ``action`` is unchanged.
    """
    from app.core.trust.audit import list_audit

    events, total = list_audit(
        limit=limit, offset=offset, run_id=run_id, resource_id=resource_id,
        action=action, q=q, with_total=True,
        category=category, exclude_category=exclude_category,
        actor=actor, user_id=user_id, credential_id=credential_id, worker_id=worker_id,
        since=since, until=until,
    )
    return {
        "events": events,
        "limit": limit,
        "offset": offset,
        "total": total,
        "has_more": offset + len(events) < total,
    }


_EXPORT_COLUMNS = (
    "timestamp", "actor", "actor_verified", "actor_kind", "action", "result", "resource_type", "resource_id",
    "principal_kind", "auth_method", "user_id", "credential_id", "worker_id", "roles", "request_id",
    "event_id", "event_hash",
)


@router.get("/audit/export", summary="Export audit events for QA (JSONL or CSV)")
def export_audit(
    format: str = Query("jsonl", pattern="^(jsonl|csv)$"),
    limit: int = Query(50000, ge=1, le=200000),
    action: str | None = Query(None),
    q: str | None = Query(None),
    category: str | None = Query(None),
    actor: str | None = Query(None),
    user_id: str | None = Query(None),
    credential_id: str | None = Query(None),
    worker_id: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    run_id: str | None = Query(None),
):
    """Filtered audit export; the download itself is audited (``audit.export``)."""
    import csv
    import io
    import json

    from fastapi.responses import Response

    from app.core.trust.audit import list_audit, record_audit, verify_audit_chain

    events = list_audit(
        limit=limit, max_limit=200000, action=action, q=q, category=category, actor=actor,
        user_id=user_id, credential_id=credential_id, worker_id=worker_id, since=since, until=until,
        run_id=run_id,
    )
    chain = verify_audit_chain()
    record_audit(
        actor="api", action="audit.export", resource_type="audit", resource_id=format,
        meta={"count": len(events), "chain_ok": chain["ok"],
              "filters": {k: v for k, v in {"action": action, "actor": actor, "user_id": user_id,
                                            "worker_id": worker_id, "since": since, "until": until,
                                            "run_id": run_id, "q": q, "category": category}.items() if v}},
    )
    headers = {
        "Content-Disposition": f'attachment; filename="graphyn-audit.{format}"',
        "X-Graphyn-Audit-Chain": "ok" if chain["ok"] else "broken",
        "X-Graphyn-Audit-Count": str(len(events)),
    }
    if format == "jsonl":
        body = "".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in events)
        return Response(content=body, media_type="application/x-ndjson", headers=headers)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_EXPORT_COLUMNS)
    for e in events:
        pr = e.get("principal") if isinstance(e.get("principal"), dict) else {}
        row = {
            **e,
            "principal_kind": pr.get("kind"),
            "auth_method": pr.get("auth_method"),
            "user_id": pr.get("user_id"),
            "credential_id": pr.get("credential_id"),
            "worker_id": pr.get("worker_id") or pr.get("mtls_worker_id"),
            "roles": ",".join(pr.get("roles") or []),
        }
        w.writerow(["" if row.get(c) is None else row.get(c) for c in _EXPORT_COLUMNS])
    return Response(content=buf.getvalue(), media_type="text/csv", headers=headers)


@router.get("/audit/verify", summary="Verify the audit log hash chain")
def verify_audit():
    from app.core.trust.audit import verify_audit_chain

    return verify_audit_chain()
