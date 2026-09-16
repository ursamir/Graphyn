# app/core/skip_logic.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Shared skip / unproduced-port decisions for sequential and
                  parallel executors (theme T1 / P1-1..P1-3).
Owns:             should_skip_for_unproduced(), mark_skipped()
Public Surface:   should_skip_for_unproduced
Must NOT:         Import app.domain or app.api.
Dependencies:     typing only.
Reason To Change: Branching / skip semantics change.
"""
from __future__ import annotations

from typing import Any, Mapping


def should_skip_for_unproduced(
    *,
    node_id: str,
    node: Any,
    incoming: Mapping[str, list[tuple[str, str, str]]],
    node_outputs: Mapping[str, Any],
    skipped: set[str],
    edge_conditions: Mapping[tuple[str, str, str, str], Any] | None,
    condition_results: Mapping[tuple[str, str, str], bool] | None = None,
) -> tuple[bool, str | None]:
    """Return (skip, reason) when a required input is unproduced.

    Unproduced means:
    - upstream node is in *skipped*, or
    - upstream output dict omits the source port (branch not taken), or
    - an edge condition evaluated to False.
    """
    edge_conditions = edge_conditions or {}
    condition_results = condition_results or {}
    for port_name, port in getattr(node, "input_ports", {}).items():
        if not getattr(port, "required", False):
            continue
        edges = [
            (src_id, src_port, dst_port)
            for src_id, src_port, dst_port in incoming.get(node_id, [])
            if dst_port == port_name
        ]
        if not edges:
            continue
        produced = False
        blocked_by_condition = False
        for src_id, src_port, dst_port in edges:
            if src_id in skipped:
                continue
            condition = edge_conditions.get((src_id, src_port, node_id, dst_port))
            if condition is not None:
                cached = condition_results.get((src_id, src_port, dst_port))
                if cached is False:
                    blocked_by_condition = True
                    continue
            upstream = node_outputs.get(src_id)
            if not isinstance(upstream, dict):
                continue
            if src_port not in upstream:
                # Branch-style nodes omit the inactive port.
                continue
            produced = True
            break
        if produced:
            continue
        if blocked_by_condition:
            return True, "condition_false"
        return True, "upstream_skipped"
    return False, None
