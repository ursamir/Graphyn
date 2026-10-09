"""
Org data residency / region pinning (Wave 4 / F15).

Each organization may declare a ``region`` (e.g. ``us-east-1``, ``eu-west-1``,
``ap-south-1``). Mode B blob and workspace placement check that the worker's
local residency matches the org's pinned region when enforcement is on.

Env
---
GRAPHYN_RESIDENCY_REGION
    This node's declared region (worker/API host). Empty = unconstrained node.
GRAPHYN_RESIDENCY_ENFORCE
    ``0`` (default) — log mismatches only.
    ``1`` / ``true`` / ``fail-closed`` — refuse blob put / workspace bind when
    org.region is set and does not match this node's region.
GRAPHYN_RESIDENCY_STRICT_UNSET
    When enforce=1 and org.region is empty: ``0`` (default) allow;
    ``1`` refuse (orgs must pin a region).

Not a substitute for cloud region controls — this pins *logical* placement for
self-hosted Mode B nodes. Document your physical region mapping in ops runbooks.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class ResidencyError(RuntimeError):
    """Region mismatch under fail-closed policy."""

    def __init__(self, message: str, *, org_region: str = "", node_region: str = ""):
        super().__init__(message)
        self.org_region = org_region
        self.node_region = node_region


def node_region() -> str:
    return (os.environ.get("GRAPHYN_RESIDENCY_REGION") or "").strip().lower()


def residency_enforce() -> bool:
    v = (os.environ.get("GRAPHYN_RESIDENCY_ENFORCE") or "0").strip().lower()
    return v in ("1", "true", "yes", "on", "fail-closed", "fail_closed")


def residency_strict_unset() -> bool:
    v = (os.environ.get("GRAPHYN_RESIDENCY_STRICT_UNSET") or "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def normalize_region(value: str | None) -> str:
    return (value or "").strip().lower()


def check_org_region(org_region: str | None, *, action: str = "placement") -> None:
    """Raise ResidencyError when fail-closed and regions disagree.

    Call before Mode B blob put / workspace materialize for an org-scoped op.
    """
    org = normalize_region(org_region)
    node = node_region()
    if not residency_enforce():
        if org and node and org != node:
            logger.warning(
                "residency mismatch (enforce=off) action=%s org=%s node=%s",
                action,
                org,
                node,
            )
        return
    if not org:
        if residency_strict_unset():
            raise ResidencyError(
                f"residency fail-closed: org has no region pinned ({action})",
                org_region=org,
                node_region=node,
            )
        return
    if not node:
        raise ResidencyError(
            f"residency fail-closed: node GRAPHYN_RESIDENCY_REGION unset but "
            f"org pinned to {org!r} ({action})",
            org_region=org,
            node_region=node,
        )
    if org != node:
        raise ResidencyError(
            f"residency fail-closed: org region {org!r} != node {node!r} ({action})",
            org_region=org,
            node_region=node,
        )


def residency_status() -> dict[str, Any]:
    return {
        "node_region": node_region() or None,
        "enforce": residency_enforce(),
        "strict_unset": residency_strict_unset(),
        "note": (
            "Logical Mode B placement pin. Map node_region to physical "
            "datacenter/cloud region in ops runbooks. Not a cloud IAM substitute."
        ),
    }


def assert_blob_placement(org_region: str | None) -> None:
    check_org_region(org_region, action="blob_put")


def assert_workspace_placement(org_region: str | None) -> None:
    check_org_region(org_region, action="workspace")
