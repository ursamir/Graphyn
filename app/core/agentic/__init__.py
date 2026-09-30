# app/core/agentic/__init__.py
"""
Bounded Context:  Agentic Builder
Responsibility:   Public API for graph proposals and human approval.
Owns:             Re-exports of proposal create/list/get/accept/reject/diff.
Public Surface:   create_proposal, list_proposals, get_proposal, accept_proposal,
                  reject_proposal, diff_graphs.
Must NOT:         Execute a graph. Must not import app.api.
Dependencies:     app.core.agentic.proposals
Reason To Change: The proposal API gains or drops a public function.
"""
from __future__ import annotations

from app.core.agentic.proposals import (
    accept_proposal,
    create_proposal,
    diff_graphs,
    get_proposal,
    list_proposals,
    reject_proposal,
)

__all__ = [
    "accept_proposal",
    "create_proposal",
    "diff_graphs",
    "get_proposal",
    "list_proposals",
    "reject_proposal",
]
