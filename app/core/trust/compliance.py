"""
Compliance export pack + audit retention (Wave 4 / F15).

Builds a zip bundle suitable for auditor handoff:
  - audit events (JSONL, retention-window filtered)
  - org / region / KMS status snapshots
  - retention policy metadata
  - TRUST_MODEL + ENTERPRISE_READINESS excerpts when present

Retention
---------
GRAPHYN_AUDIT_RETENTION_DAYS
    Soft retention window for exports and optional prune (default 365).
    ``0`` = no time filter on export (full history still subject to store limits).
GRAPHYN_AUDIT_RETENTION_ENFORCE
    When ``1``, ``prune_expired_audit`` may delete events older than the window
    (opt-in; default off so labs keep history).

HTTP: ``GET /api/v1/compliance/export`` (admin) and ``GET /api/v1/compliance/status``.
MCP: ``graphyn_compliance_export`` when MCP tools are registered.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[3]


def audit_retention_days() -> int:
    raw = (os.environ.get("GRAPHYN_AUDIT_RETENTION_DAYS") or "365").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 365


def audit_retention_enforce() -> bool:
    v = (os.environ.get("GRAPHYN_AUDIT_RETENTION_ENFORCE") or "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def retention_cutoff_ts() -> float | None:
    days = audit_retention_days()
    if days <= 0:
        return None
    return time.time() - (days * 86400.0)


def retention_policy() -> dict[str, Any]:
    return {
        "retention_days": audit_retention_days(),
        "enforce_prune": audit_retention_enforce(),
        "cutoff_unix": retention_cutoff_ts(),
        "note": (
            "Export filters by retention window when retention_days > 0. "
            "Prune runs only when GRAPHYN_AUDIT_RETENTION_ENFORCE=1."
        ),
    }


def _read_doc_excerpt(name: str, max_bytes: int = 120_000) -> str | None:
    path = _REPO / "docs" / name
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="replace")
    except OSError:
        return None


def build_compliance_bundle(
    *,
    org_id: str | None = None,
    since: float | None = None,
    until: float | None = None,
    limit: int = 50_000,
) -> bytes:
    """Return zip bytes for compliance handoff."""
    from datetime import datetime, timezone as tz

    from app.core.trust.audit import list_audit
    from app.core.trust.kms import kms_status
    from app.core.trust.residency import residency_status

    cutoff = retention_cutoff_ts()
    if since is None and cutoff is not None:
        since = cutoff

    def _iso(ts: float | str | None) -> str | None:
        if ts is None:
            return None
        if isinstance(ts, str):
            return ts
        return datetime.fromtimestamp(float(ts), tz=tz.utc).isoformat()

    events = list_audit(
        limit=min(max(1, limit), 100_000),
        since=_iso(since),
        until=_iso(until),
        max_limit=100_000,
    )
    # Optional org filter via metadata/principal (audit log may not index org_id)
    if org_id:
        oid = str(org_id)
        filtered = []
        for e in events:
            meta = e.get("metadata") or e.get("meta") or {}
            pr = e.get("principal") if isinstance(e.get("principal"), dict) else {}
            if meta.get("org_id") == oid or pr.get("org_id") == oid or e.get("org_id") == oid:
                filtered.append(e)
        events = filtered

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "org_id_filter": org_id,
        "since": since,
        "until": until,
        "event_count": len(events),
        "retention": retention_policy(),
        "kms": kms_status(),
        "residency": residency_status(),
        "pack_version": "f15-compliance-1",
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(meta, indent=2, default=str))
        zf.writestr(
            "audit/events.jsonl",
            "\n".join(json.dumps(e, default=str) for e in events) + ("\n" if events else ""),
        )
        zf.writestr("policy/retention.json", json.dumps(retention_policy(), indent=2))
        zf.writestr("policy/kms_status.json", json.dumps(kms_status(), indent=2, default=str))
        zf.writestr(
            "policy/residency_status.json",
            json.dumps(residency_status(), indent=2),
        )
        for doc in ("TRUST_MODEL.md", "ENTERPRISE_READINESS.md", "SECURITY.md"):
            body = _read_doc_excerpt(doc)
            if body:
                zf.writestr(f"docs/{doc}", body)
    return buf.getvalue()


def prune_expired_audit(*, dry_run: bool = True) -> dict[str, Any]:
    """Delete audit events older than retention window when enforce is on.

    Default dry_run=True counts only. Requires store support for delete-by-age.
    """
    cutoff = retention_cutoff_ts()
    if cutoff is None:
        return {"pruned": 0, "dry_run": dry_run, "reason": "retention_days=0 (disabled)"}
    if not audit_retention_enforce() and not dry_run:
        return {
            "pruned": 0,
            "dry_run": dry_run,
            "reason": "GRAPHYN_AUDIT_RETENTION_ENFORCE not set; refusing destructive prune",
        }
    from datetime import datetime, timezone as tz

    from app.core.trust.audit import list_audit

    until_iso = datetime.fromtimestamp(float(cutoff), tz=tz.utc).isoformat()
    old = list_audit(limit=100_000, until=until_iso, max_limit=100_000)
    if dry_run or not audit_retention_enforce():
        return {
            "pruned": 0,
            "would_prune": len(old),
            "dry_run": True,
            "cutoff": cutoff,
            "reason": (
                None
                if dry_run
                else "GRAPHYN_AUDIT_RETENTION_ENFORCE not set; refusing destructive prune"
            ),
            "note": (
                "JSONL audit log has no delete_audit_before; set enforce + use "
                "external log rotation, or rely on export window filtering."
            ),
        }
    return {
        "pruned": 0,
        "would_prune": len(old),
        "dry_run": False,
        "cutoff": cutoff,
        "reason": "JSONL audit store does not support in-place prune; export filters by retention",
    }


def compliance_status() -> dict[str, Any]:
    from app.core.trust.kms import kms_status
    from app.core.trust.residency import residency_status

    return {
        "retention": retention_policy(),
        "kms": kms_status(),
        "residency": residency_status(),
        "export_endpoints": [
            "GET /api/v1/compliance/export",
            "GET /api/v1/compliance/status",
            "GET /api/v1/audit/export (existing)",
        ],
    }
