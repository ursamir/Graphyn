# app/mcp/handlers/proposals.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Agentic Builder MCP tools — agents propose GraphIR; humans or
                  agents with approval can accept/reject via MCP (same core as UI).
Owns:             propose_graph, list_proposals, get_proposal, accept_proposal,
                  reject_proposal handlers + schemas.
Public Surface:   Handler functions and SCHEMA/DESCRIPTION constants.
Must NOT:         Accept or return secrets; auto-apply graphs without human approval.
Dependencies:     app.core.agentic.proposals.
Reason To Change: Proposal tool schemas evolve.
"""
from __future__ import annotations

from typing import Any

PROPOSE_GRAPH_DESCRIPTION = (
    "Propose a GraphIR change for human approval. Stores a pending proposal under "
    "the project proposals/ directory. Does not apply the graph — a human must Accept "
    "in the Graphyn UI (Library → Proposals). Secrets must never appear in the graph."
)

PROPOSE_GRAPH_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Short human-readable description of the proposed change.",
        },
        "graph": {
            "type": "object",
            "description": "Full proposed GraphIR JSON document.",
        },
        "actor": {
            "type": "string",
            "description": "Optional agent/actor name (default: mcp).",
        },
        "base_graph": {
            "type": "object",
            "description": "Optional baseline GraphIR for a richer node/edge diff.",
        },
        "base_graph_hash": {
            "type": "string",
            "description": "Optional hash of the graph this proposal is based on.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["summary", "graph"],
    "additionalProperties": False,
}

LIST_PROPOSALS_DESCRIPTION = (
    "List GraphIR change proposals (summaries). Optionally filter by status: "
    "pending, accepted, or rejected."
)

LIST_PROPOSALS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["pending", "accepted", "rejected"],
            "description": "Optional status filter.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "additionalProperties": False,
}

GET_PROPOSAL_DESCRIPTION = (
    "Get one graph proposal by id, including proposed_graph and diff_summary."
)

GET_PROPOSAL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "id": {
            "type": "string",
            "description": "Proposal id returned by propose_graph.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["id"],
    "additionalProperties": False,
}


def propose_graph_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.agentic.proposals import create_proposal

    args = arguments or {}
    summary = args.get("summary")
    graph = args.get("graph")
    if not summary or not isinstance(summary, str) or not summary.strip():
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "propose_graph requires a non-empty 'summary'.",
        }
    if not isinstance(graph, dict) or not graph:
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "propose_graph requires a non-empty 'graph' object.",
        }
    try:
        proposal = create_proposal(
            graph,
            summary.strip(),
            actor=str(args.get("actor") or "mcp"),
            base_graph=args.get("base_graph") if isinstance(args.get("base_graph"), dict) else None,
            base_graph_hash=args.get("base_graph_hash")
            if isinstance(args.get("base_graph_hash"), str)
            else None,
        )
    except ValueError as exc:
        return {"error": True, "error_type": "invalid_argument", "message": str(exc)}

    return {
        "ok": True,
        "id": proposal["id"],
        "status": proposal["status"],
        "summary": proposal["summary"],
        "diff_summary": proposal.get("diff_summary"),
        "message": (
            "Proposal stored as pending. A human must Accept it in Graphyn UI "
            "(Library → Proposals) before the graph is loaded into Builder."
        ),
    }


def list_proposals_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.agentic.proposals import list_proposals

    args = arguments or {}
    status = args.get("status")
    if status is not None and status not in ("pending", "accepted", "rejected"):
        return {
            "error": True,
            "error_type": "invalid_argument",
            "message": "status must be pending, accepted, or rejected.",
        }
    try:
        items = list_proposals(status=status)
    except ValueError as exc:
        return {"error": True, "error_type": "invalid_argument", "message": str(exc)}
    return {"proposals": items, "count": len(items)}


def get_proposal_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.agentic.proposals import get_proposal

    args = arguments or {}
    proposal_id = args.get("id")
    if not proposal_id or not isinstance(proposal_id, str):
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "get_proposal requires 'id'.",
        }
    data = get_proposal(proposal_id.strip())
    if data is None:
        return {
            "error": True,
            "error_type": "not_found",
            "message": f"Proposal not found: {proposal_id}",
        }
    return data


ACCEPT_PROPOSAL_DESCRIPTION = (
    "Accept a pending GraphIR proposal (same as UI Accept). Marks the proposal "
    "accepted and returns it including proposed_graph for the client to load."
)

ACCEPT_PROPOSAL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Proposal id."},
        "actor": {
            "type": "string",
            "description": "Who accepted (default: mcp).",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["id"],
    "additionalProperties": False,
}

REJECT_PROPOSAL_DESCRIPTION = (
    "Reject a pending GraphIR proposal (same as UI Reject)."
)

REJECT_PROPOSAL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Proposal id."},
        "actor": {
            "type": "string",
            "description": "Who rejected (default: mcp).",
        },
        "reason": {
            "type": "string",
            "description": "Optional human-readable reject reason.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["id"],
    "additionalProperties": False,
}


def accept_proposal_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.agentic.proposals import accept_proposal

    args = arguments or {}
    proposal_id = args.get("id")
    if not proposal_id or not isinstance(proposal_id, str):
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "accept_proposal requires 'id'.",
        }
    actor = args.get("actor") if isinstance(args.get("actor"), str) else "mcp"
    try:
        data = accept_proposal(proposal_id.strip(), actor=(actor or "mcp").strip() or "mcp")
    except KeyError:
        return {
            "error": True,
            "error_type": "not_found",
            "message": f"Proposal not found: {proposal_id}",
        }
    except ValueError as exc:
        return {
            "error": True,
            "error_type": "invalid_state",
            "message": str(exc),
        }
    return {"ok": True, **data}


def reject_proposal_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.agentic.proposals import reject_proposal

    args = arguments or {}
    proposal_id = args.get("id")
    if not proposal_id or not isinstance(proposal_id, str):
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "reject_proposal requires 'id'.",
        }
    actor = args.get("actor") if isinstance(args.get("actor"), str) else "mcp"
    reason = args.get("reason") if isinstance(args.get("reason"), str) else None
    try:
        data = reject_proposal(
            proposal_id.strip(),
            actor=(actor or "mcp").strip() or "mcp",
            reason=reason,
        )
    except KeyError:
        return {
            "error": True,
            "error_type": "not_found",
            "message": f"Proposal not found: {proposal_id}",
        }
    except ValueError as exc:
        return {
            "error": True,
            "error_type": "invalid_state",
            "message": str(exc),
        }
    return {"ok": True, **data}
