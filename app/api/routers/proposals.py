# app/api/routers/proposals.py
"""
Bounded Context:  REST API Layer
Responsibility:   Agentic Builder proposal endpoints (propose / list / accept / reject).
Owns:             POST/GET /proposals, GET /proposals/{id},
                  POST /proposals/{id}/accept, POST /proposals/{id}/reject.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain storage logic — delegate to app.core.agentic.proposals.
Dependencies:     fastapi, pydantic, app.core.agentic.proposals.
Reason To Change: Proposal API schema changes.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
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


class ResolveBody(BaseModel):
    actor: Optional[str] = Field(None, description="Who accepted/rejected (default human)")
    reason: Optional[str] = Field(None, description="Optional reject reason")


@router.post("", summary="Create a graph change proposal")
def create_proposal_endpoint(body: CreateProposalBody):
    """Store a pending GraphIR proposal for human approval."""
    from app.core.agentic.proposals import create_proposal

    try:
        return create_proposal(
            body.graph,
            body.summary,
            actor=body.actor or "api",
            base_graph=body.base_graph,
            base_graph_hash=body.base_graph_hash,
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


@router.post("/{proposal_id}/accept", summary="Accept a proposal")
def accept_proposal_endpoint(proposal_id: str, body: ResolveBody | None = None):
    """Accept proposal, audit, and return it so the client can load the graph."""
    from app.core.agentic.proposals import accept_proposal

    actor = (body.actor if body else None) or "human"
    try:
        return accept_proposal(proposal_id, actor=actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{proposal_id}/reject", summary="Reject a proposal")
def reject_proposal_endpoint(proposal_id: str, body: ResolveBody | None = None):
    """Reject proposal and record audit."""
    from app.core.agentic.proposals import reject_proposal

    actor = (body.actor if body else None) or "human"
    reason = body.reason if body else None
    try:
        return reject_proposal(proposal_id, actor=actor, reason=reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
