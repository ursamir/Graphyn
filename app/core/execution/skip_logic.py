# app/core/execution/skip_logic.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Shared skip / unproduced-port decisions for sequential and
                  parallel executors (theme T1 / P1-1..P1-3).
Owns:             should_skip_for_unproduced() (rule 1: unproduced required
                  input; rule 2: every incoming edge unproduced — G1)
Public Surface:   should_skip_for_unproduced
Must NOT:         Import app.domain or app.api.
Dependencies:     typing only.
Reason To Change: Branching / skip semantics change.
"""
from __future__ import annotations

from typing import Any, Mapping


def _edge_produced(
    edge: tuple[str, str, str],
    *,
    node_id: str,
    node_outputs: Mapping[str, Any],
    skipped: set[str],
    edge_conditions: Mapping[tuple[str, str, str, str], Any],
    condition_results: Mapping[tuple[str, str, str], bool],
) -> tuple[bool, bool]:
    """Return ``(produced, blocked_by_condition)`` for one incoming data edge."""
    src_id, src_port, dst_port = edge
    if src_id in skipped:
        return False, False
    condition = edge_conditions.get((src_id, src_port, node_id, dst_port))
    if condition is not None and condition_results.get((src_id, src_port, dst_port)) is False:
        return False, True
    upstream = node_outputs.get(src_id)
    if not isinstance(upstream, dict):
        return False, False
    if src_port not in upstream:
        # Branch-style nodes omit the inactive port.
        return False, False
    return True, False


def should_skip_for_unproduced(
    *,
    node_id: str,
    node: Any,
    incoming: Mapping[str, list[tuple[str, str, str]]],
    node_outputs: Mapping[str, Any],
    skipped: set[str],
    edge_conditions: Mapping[tuple[str, str, str, str], Any] | None,
    condition_results: Mapping[tuple[str, str, str], bool] | None = None,
    provided_ports: set[str] | frozenset[str] | None = None,
) -> tuple[bool, str | None]:
    """Return (skip, reason) when a node's inputs are unproduced.

    An incoming edge is *unproduced* when:
    - the upstream node is in *skipped*, or
    - the upstream output dict omits the source port (branch not taken), or
    - an edge condition evaluated to False.

    Two rules (G1), applied identically by the sequential and parallel paths:

    1. **Required input** — skip when any *required* input port has incoming
       edges and none of them is produced.
    2. **All inputs unproduced** — skip when the node has at least one
       incoming data edge and EVERY incoming edge is unproduced, regardless
       of ``required``. This keeps the not-taken branch of ``if_switch`` /
       ``hitl_approve`` from running with ``None`` on optional ports. A node
       with SOME produced input still runs (e.g. ``merge`` with one side).

    *provided_ports* are ports whose value is already supplied out-of-band
    (input overrides, values from an inactive/excluded source). Edges into
    those ports never count as unproduced, and any provided port means the
    node has a produced input (rule 2 does not apply).
    """
    edge_conditions = edge_conditions or {}
    condition_results = condition_results or {}
    provided = set(provided_ports or ())
    all_edges = list(incoming.get(node_id, []))
    edges = [e for e in all_edges if e[2] not in provided]

    status: dict[tuple[str, str, str], tuple[bool, bool]] = {
        e: _edge_produced(
            e,
            node_id=node_id,
            node_outputs=node_outputs,
            skipped=skipped,
            edge_conditions=edge_conditions,
            condition_results=condition_results,
        )
        for e in edges
    }

    # Rule 1 — required ports (unchanged behaviour).
    for port_name, port in getattr(node, "input_ports", {}).items():
        if not getattr(port, "required", False):
            continue
        port_edges = [e for e in edges if e[2] == port_name]
        if not port_edges:
            continue
        if any(status[e][0] for e in port_edges):
            continue
        if any(status[e][1] for e in port_edges):
            return True, "condition_false"
        return True, "upstream_skipped"

    # Rule 2 — every incoming data edge unproduced (optional ports included).
    if provided or not edges:
        return False, None
    if any(produced for produced, _ in status.values()):
        return False, None
    if any(blocked for _, blocked in status.values()):
        return True, "condition_false"
    return True, "all_inputs_unproduced"
