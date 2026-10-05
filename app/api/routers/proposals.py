# app/api/routers/proposals.py
"""
Bounded Context:  REST API Layer
Responsibility:   Agentic Builder proposal endpoints (propose / list / accept / reject).
Owns:             POST/GET /proposals, GET /proposals/{id},
                  POST /proposals/{id}/accept, POST /proposals/{id}/reject.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain storage logic — delegate to app.core.agentic.proposals.
Dependencies:     fastapi, pydantic, app.core.agentic.proposals, app.api.actor
                  (token-bound actor for create / accept / reject).
Reason To Change: Proposal API schema changes.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/proposals", tags=["proposals"])


class CreateProposalBody(BaseModel):
    summary: str = Field(..., min_length=1, description="Human-readable proposal summary")
    graph: dict[str, Any] = Field(..., description="Proposed GraphIR document")
    actor: Optional[str] = Field(None, description="Who proposed (agent name / mcp / api)")
    base_graph: Optional[dict[str, Any]] = Field(
        None, description="Optional baseline GraphIR for richer diffs"
    )
    base_graph_hash: Optional[str] = Field(
        None, description="Optional hash of the graph this proposal is based on"
    )
    kind: Optional[str] = Field(
        None,
        max_length=64,
        description='Optional proposal kind, e.g. "explain_failure"',
    )
    context: Optional[dict[str, Any]] = Field(
        None,
        description="Optional structured context, e.g. {run_id, node_id, error} (<=16 KiB)",
    )


class ResolveBody(BaseModel):
    actor: Optional[str] = Field(None, description="Who accepted/rejected (default human)")
    reason: Optional[str] = Field(None, description="Optional reject reason")


@router.post("", summary="Create a graph change proposal")
def create_proposal_endpoint(body: CreateProposalBody, request: Request):
    """Store a pending GraphIR proposal for human approval."""
    from app.api.actor import resolve_actor
    from app.core.agentic.proposals import create_proposal

    try:
        return create_proposal(
            body.graph,
            body.summary,
            actor=resolve_actor(request, body.actor),
            base_graph=body.base_graph,
            base_graph_hash=body.base_graph_hash,
            kind=body.kind,
            context=body.context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", summary="List graph proposals")
def list_proposals_endpoint(
    status: Optional[str] = Query(
        None, description="Filter: pending | accepted | rejected"
    ),
):
    """Return proposal summaries newest-first."""
    from app.core.agentic.proposals import list_proposals

    try:
        return {"proposals": list_proposals(status=status)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{proposal_id}", summary="Get one proposal")
def get_proposal_endpoint(proposal_id: str):
    """Return the full proposal including ``proposed_graph`` and ``diff_summary``."""
    from app.core.agentic.proposals import get_proposal

    data = get_proposal(proposal_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Proposal not found: {proposal_id}")
    return data


def _resolver_actor(request: Request, body: "ResolveBody | None") -> str:
    """Token-mapped name > body actor > X-Actor > ``unidentified`` (app.api.actor).

    With a mapped bearer token a differing body / header actor is recorded
    only as ``claimed_actor`` on the audit event.
    """
    from app.api.actor import resolve_actor

    return resolve_actor(request, body.actor if body else None)


@router.post("/{proposal_id}/accept", summary="Accept a proposal")
def accept_proposal_endpoint(
    proposal_id: str,
    request: Request,
    body: ResolveBody | None = None,
):
    """Accept proposal, audit, and return it so the client can load the graph.

    Honors Idempotency-Key (API-CONV-004).
    """
    from app.api.idempotency import begin_idempotent, complete_idempotent, idempotency_guard
    from app.core.agentic.proposals import accept_proposal

    body_data = body.model_dump() if body is not None else {}
    cached = begin_idempotent(
        request,
        body={"proposal_id": proposal_id, **body_data},
        route=f"POST /api/v1/proposals/{{id}}/accept",
    )
    if cached is not None:
        return cached

    with idempotency_guard(request):
        actor = _resolver_actor(request, body)
        try:
            result = accept_proposal(proposal_id, actor=actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        complete_idempotent(request, status_code=200, body=result)
    return result


@router.post("/{proposal_id}/reject", summary="Reject a proposal")
def reject_proposal_endpoint(
    proposal_id: str,
    request: Request,
    body: ResolveBody | None = None,
):
    """Reject proposal and record audit."""
    from app.core.agentic.proposals import reject_proposal

    actor = _resolver_actor(request, body)
    reason = body.reason if body else None
    try:
        return reject_proposal(proposal_id, actor=actor, reason=reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
