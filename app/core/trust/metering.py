# app/core/trust/metering.py
"""
Bounded Context:  BC6 — Observability & Storage (tenancy / billing seam)
Responsibility:   Per-org quotas, usage counters, and append-only metering
                  events that a billing system can consume (Stripe webhook
                  seam, export API). Not a full billing product — hooks only.
Owns:             MeterStore, get_meter_store(), reset_meter_store(),
                  record_meter_event(), check_quota(), OrgQuota, OrgUsage,
                  MeterStoreError, DEFAULT_QUOTAS.
Public Surface:   The names above.
Must NOT:         Charge cards or call Stripe directly; import app.api.
Dependencies:     stdlib, app.core.trust.orgs (same users.db path).
Reason To Change: Quota dimensions or metering event schema change.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_QUOTAS: dict[str, int | None] = {
    "max_seats": 50,
    "max_projects": 100,
    "max_runs_per_day": 1000,
    "max_credentials": 200,
    # F18: concurrent claimed/running jobs + pending queue depth per org
    "max_concurrent_jobs": 8,
    "max_queued_jobs": 100,
}

_STORE: "MeterStore | None" = None
_STORE_PATH: Path | None = None
_STORE_LOCK = threading.RLock()


class MeterStoreError(ValueError):
    def __init__(self, message: str, status_code: int = 400, code: str = "quota_exceeded") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass
class OrgQuota:
    org_id: str
    max_seats: int | None
    max_projects: int | None
    max_runs_per_day: int | None
    max_credentials: int | None
    max_concurrent_jobs: int | None
    max_queued_jobs: int | None
    updated_at: float
    updated_by: str | None

    def public(self) -> dict[str, Any]:
        return {
            "org_id": self.org_id,
            "max_seats": self.max_seats,
            "max_projects": self.max_projects,
            "max_runs_per_day": self.max_runs_per_day,
            "max_credentials": self.max_credentials,
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "max_queued_jobs": self.max_queued_jobs,
            "updated_at": _iso(self.updated_at),
            "updated_by": self.updated_by,
        }


@dataclass
class OrgUsage:
    org_id: str
    seats: int
    projects: int
    runs_today: int
    credentials: int
    meter_events: int
    concurrent_jobs: int = 0
    queued_jobs: int = 0

    def public(self) -> dict[str, Any]:
        return {
            "org_id": self.org_id,
            "seats": self.seats,
            "projects": self.projects,
            "runs_today": self.runs_today,
            "credentials": self.credentials,
            "meter_events": self.meter_events,
            "concurrent_jobs": self.concurrent_jobs,
            "queued_jobs": self.queued_jobs,
        }


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS org_quotas (
  org_id TEXT PRIMARY KEY,
  max_seats INTEGER,
  max_projects INTEGER,
  max_runs_per_day INTEGER,
  max_credentials INTEGER,
  max_concurrent_jobs INTEGER,
  max_queued_jobs INTEGER,
  updated_at REAL NOT NULL,
  updated_by TEXT
);
CREATE TABLE IF NOT EXISTS meter_events (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  quantity REAL NOT NULL DEFAULT 1,
  resource_type TEXT,
  resource_id TEXT,
  actor TEXT,
  created_at REAL NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS meter_events_org_time ON meter_events(org_id, created_at);
CREATE TABLE IF NOT EXISTS billing_webhook_deliveries (
  id TEXT PRIMARY KEY,
  received_at REAL NOT NULL,
  event_type TEXT,
  payload_sha256 TEXT NOT NULL,
  result TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
"""


class MeterStore:
    def __init__(self, path: Path | str | None = None) -> None:
        from app.core.trust.users import default_store_path

        self.path = Path(path) if path is not None else default_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._conn() as c:
            c.executescript(_SCHEMA)
            cols = {r[1] for r in c.execute("PRAGMA table_info(org_quotas)").fetchall()}
            if "max_concurrent_jobs" not in cols:
                c.execute("ALTER TABLE org_quotas ADD COLUMN max_concurrent_jobs INTEGER")
            if "max_queued_jobs" not in cols:
                c.execute("ALTER TABLE org_quotas ADD COLUMN max_queued_jobs INTEGER")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def get_quota(self, org_id: str) -> OrgQuota:
        with self._conn() as c:
            row = c.execute("SELECT * FROM org_quotas WHERE org_id=?", (org_id,)).fetchone()
        if row is None:
            return OrgQuota(
                org_id=org_id,
                max_seats=DEFAULT_QUOTAS["max_seats"],
                max_projects=DEFAULT_QUOTAS["max_projects"],
                max_runs_per_day=DEFAULT_QUOTAS["max_runs_per_day"],
                max_credentials=DEFAULT_QUOTAS["max_credentials"],
                max_concurrent_jobs=DEFAULT_QUOTAS["max_concurrent_jobs"],
                max_queued_jobs=DEFAULT_QUOTAS["max_queued_jobs"],
                updated_at=0.0,
                updated_by=None,
            )
        keys = row.keys()
        conc = row["max_concurrent_jobs"] if "max_concurrent_jobs" in keys else None
        queued = row["max_queued_jobs"] if "max_queued_jobs" in keys else None
        if conc is None:
            conc = DEFAULT_QUOTAS["max_concurrent_jobs"]
        if queued is None:
            queued = DEFAULT_QUOTAS["max_queued_jobs"]
        return OrgQuota(
            org_id=row["org_id"],
            max_seats=row["max_seats"],
            max_projects=row["max_projects"],
            max_runs_per_day=row["max_runs_per_day"],
            max_credentials=row["max_credentials"],
            max_concurrent_jobs=conc,
            max_queued_jobs=queued,
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
        )

    def set_quota(
        self,
        org_id: str,
        *,
        max_seats: int | None = None,
        max_projects: int | None = None,
        max_runs_per_day: int | None = None,
        max_credentials: int | None = None,
        max_concurrent_jobs: int | None = None,
        max_queued_jobs: int | None = None,
        updated_by: str | None = None,
    ) -> OrgQuota:
        cur = self.get_quota(org_id)
        seats = max_seats if max_seats is not None else cur.max_seats
        projects = max_projects if max_projects is not None else cur.max_projects
        runs = max_runs_per_day if max_runs_per_day is not None else cur.max_runs_per_day
        creds = max_credentials if max_credentials is not None else cur.max_credentials
        conc = max_concurrent_jobs if max_concurrent_jobs is not None else cur.max_concurrent_jobs
        queued = max_queued_jobs if max_queued_jobs is not None else cur.max_queued_jobs
        for label, val in (
            ("max_seats", seats),
            ("max_projects", projects),
            ("max_runs_per_day", runs),
            ("max_credentials", creds),
            ("max_concurrent_jobs", conc),
            ("max_queued_jobs", queued),
        ):
            if val is not None and int(val) < 0:
                raise MeterStoreError(f"{label} must be >= 0", 400, "validation_failed")
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO org_quotas (org_id, max_seats, max_projects, max_runs_per_day, max_credentials,"
                " max_concurrent_jobs, max_queued_jobs, updated_at, updated_by)"
                " VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(org_id) DO UPDATE SET max_seats=excluded.max_seats, max_projects=excluded.max_projects,"
                " max_runs_per_day=excluded.max_runs_per_day, max_credentials=excluded.max_credentials,"
                " max_concurrent_jobs=excluded.max_concurrent_jobs, max_queued_jobs=excluded.max_queued_jobs,"
                " updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                (org_id, seats, projects, runs, creds, conc, queued, time.time(), updated_by),
            )
        return self.get_quota(org_id)

    def record_event(
        self,
        org_id: str,
        event_type: str,
        *,
        quantity: float = 1.0,
        resource_type: str | None = None,
        resource_id: str | None = None,
        actor: str | None = None,
        meta: dict | None = None,
    ) -> dict[str, Any]:
        eid = "m_" + uuid.uuid4().hex[:16]
        now = time.time()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO meter_events (id, org_id, event_type, quantity, resource_type, resource_id, actor, created_at, meta)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    eid,
                    org_id,
                    str(event_type or "").strip()[:64],
                    float(quantity),
                    resource_type,
                    resource_id,
                    actor,
                    now,
                    json.dumps(meta or {}, separators=(",", ":")),
                ),
            )
        return {
            "id": eid,
            "org_id": org_id,
            "event_type": event_type,
            "quantity": quantity,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "actor": actor,
            "created_at": _iso(now),
            "meta": meta or {},
        }

    def list_events(self, org_id: str, *, since: float | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM meter_events WHERE org_id=?"
        args: list[Any] = [org_id]
        if since is not None:
            sql += " AND created_at>=?"
            args.append(float(since))
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(int(limit), 1000)))
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        out = []
        for r in rows:
            try:
                meta = json.loads(r["meta"] or "{}")
            except Exception:
                meta = {}
            out.append(
                {
                    "id": r["id"],
                    "org_id": r["org_id"],
                    "event_type": r["event_type"],
                    "quantity": r["quantity"],
                    "resource_type": r["resource_type"],
                    "resource_id": r["resource_id"],
                    "actor": r["actor"],
                    "created_at": _iso(r["created_at"]),
                    "meta": meta,
                }
            )
        return out

    def usage(self, org_id: str) -> OrgUsage:
        from app.core.trust.orgs import get_org_store

        store = get_org_store()
        seats = len(store.org_members(org_id))
        # Count only explicitly mapped projects (not legacy unmapped-on-disk expansion).
        with store._conn() as c:
            projects = c.execute("SELECT COUNT(*) FROM org_projects WHERE org_id=?", (org_id,)).fetchone()[0]
        day_start = time.time() - (time.time() % 86400)
        with self._conn() as c:
            runs = c.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM meter_events WHERE org_id=? AND event_type='run.started' AND created_at>=?",
                (org_id, day_start),
            ).fetchone()[0]
            events = c.execute("SELECT COUNT(*) FROM meter_events WHERE org_id=?", (org_id,)).fetchone()[0]
        # credentials count via credential store
        creds = 0
        try:
            from app.core.credentials.store import list_connections

            creds = len(list_connections(org_id=org_id))
        except Exception:
            pass
        concurrent = 0
        queued_n = 0
        try:
            from app.core.distributed.quotas import count_org_jobs

            concurrent = count_org_jobs(org_id, statuses=("claimed", "running"))
            queued_n = count_org_jobs(org_id, statuses=("pending",))
        except Exception:
            pass
        return OrgUsage(
            org_id=org_id,
            seats=int(seats),
            projects=int(projects),
            runs_today=int(runs or 0),
            credentials=int(creds),
            meter_events=int(events or 0),
            concurrent_jobs=int(concurrent),
            queued_jobs=int(queued_n),
        )

    def check_quota(self, org_id: str, dimension: str, *, upcoming: int = 1) -> None:
        """Raise MeterStoreError when adding ``upcoming`` would exceed the quota."""
        q = self.get_quota(org_id)
        u = self.usage(org_id)
        limits = {
            "seats": (q.max_seats, u.seats),
            "projects": (q.max_projects, u.projects),
            "runs_per_day": (q.max_runs_per_day, u.runs_today),
            "credentials": (q.max_credentials, u.credentials),
            "concurrent_jobs": (q.max_concurrent_jobs, u.concurrent_jobs),
            "queued_jobs": (q.max_queued_jobs, u.queued_jobs),
        }
        if dimension not in limits:
            raise MeterStoreError(f"Unknown quota dimension '{dimension}'", 400, "validation_failed")
        limit, used = limits[dimension]
        if limit is None:
            return
        if used + upcoming > int(limit):
            raise MeterStoreError(
                f"Organization quota exceeded for {dimension} (used {used}, limit {limit})",
                409,
                "quota_exceeded",
            )

    def record_webhook_delivery(self, event_type: str | None, payload: bytes, result: str, detail: str = "") -> str:
        wid = "bw_" + uuid.uuid4().hex[:12]
        digest = hashlib.sha256(payload).hexdigest()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO billing_webhook_deliveries (id, received_at, event_type, payload_sha256, result, detail)"
                " VALUES (?,?,?,?,?,?)",
                (wid, time.time(), event_type, digest, result, detail[:512]),
            )
        return wid


    def list_webhook_deliveries(self, *, limit: int = 50) -> list[dict[str, Any]]:
        lim = max(1, min(int(limit), 500))
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, received_at, event_type, payload_sha256, result, detail "
                "FROM billing_webhook_deliveries ORDER BY received_at DESC LIMIT ?",
                (lim,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "received_at": _iso(r["received_at"]),
                "event_type": r["event_type"],
                "payload_sha256": r["payload_sha256"],
                "result": r["result"],
                "detail": r["detail"],
            }
            for r in rows
        ]

    def billing_webhook_status(self) -> dict[str, Any]:
        import os

        secret_set = bool((os.environ.get("GRAPHYN_BILLING_WEBHOOK_SECRET") or "").strip())
        recent = self.list_webhook_deliveries(limit=10)
        accepted = sum(1 for d in recent if d.get("result") == "accepted")
        rejected = sum(1 for d in recent if d.get("result") == "rejected")
        return {
            "secret_configured": secret_set,
            "checkout_ui": "Not shipped — no Stripe Checkout / payment method UI (hooks only)",
            "endpoint": "POST /api/v1/billing/webhook",
            "recent_deliveries": recent,
            "recent_accepted": accepted,
            "recent_rejected": rejected,
            "note": (
                "Admin metering/usage is available under org usage APIs. "
                "This is not a full SaaS billing product."
            ),
        }


def verify_billing_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Stripe-style ``sha256=HMAC(secret, body)`` using GRAPHYN_BILLING_WEBHOOK_SECRET."""
    secret = (os.environ.get("GRAPHYN_BILLING_WEBHOOK_SECRET") or "").strip()
    if not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    got = str(signature_header or "").strip()
    return bool(got) and hmac.compare_digest(expected, got)


def get_meter_store() -> MeterStore:
    global _STORE, _STORE_PATH
    from app.core.trust.users import default_store_path

    path = default_store_path()
    with _STORE_LOCK:
        if _STORE is None or _STORE_PATH != path:
            _STORE = MeterStore(path)
            _STORE_PATH = path
        return _STORE


def reset_meter_store() -> None:
    global _STORE, _STORE_PATH
    with _STORE_LOCK:
        _STORE = None
        _STORE_PATH = None


def record_meter_event(org_id: str | None, event_type: str, **kwargs: Any) -> dict[str, Any] | None:
    if not org_id:
        return None
    try:
        return get_meter_store().record_event(org_id, event_type, **kwargs)
    except Exception:
        return None


__all__ = [
    "DEFAULT_QUOTAS",
    "MeterStore",
    "MeterStoreError",
    "OrgQuota",
    "OrgUsage",
    "get_meter_store",
    "record_meter_event",
    "reset_meter_store",
    "verify_billing_webhook_signature",
    "list_webhook_deliveries",
]
