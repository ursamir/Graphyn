# app/core/trust/agents.py
"""
Bounded Context:  BC6 — Trust (agent / MCP principals)
Responsibility:   Admin-managed agent identities with scoped roles and
                  project memberships. Agents authenticate via opaque
                  ``gxa_…`` credentials (kind=agent) for API and MCP.
Owns:             Agent, AgentStore, get_agent_store(), reset_agent_store(),
                  AgentStoreError, AGENT_ROLES.
Public Surface:   Those names.
Must NOT:         Fake OIDC client_credentials or payment/agent SSO stubs.
Dependencies:     stdlib, app.core.trust.users (same SQLite path).
Reason To Change: Agent schema, token minting, or role policy.

OIDC service-account link: optional ``oidc_client_id`` is stored as an audit
label only. Live client_credentials exchange is **not** shipped here — mint
admin-managed tokens instead (honest Wave 6 scope).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.trust.users import ROLE_NAMES, UserStoreError, get_user_store

AGENT_ROLES: tuple[str, ...] = tuple(r for r in ROLE_NAMES if r != "admin")  # admin optional via explicit grant
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")

_STORE: "AgentStore | None" = None
_STORE_LOCK = threading.RLock()


class AgentStoreError(UserStoreError):
    """Agent validation / conflict."""


@dataclass
class Agent:
    id: str
    slug: str
    name: str
    roles: list[str]
    memberships: dict[str, str]
    org_id: str | None
    disabled: bool
    created_at: float
    created_by: str | None
    oidc_client_id: str | None = None
    notes: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "roles": list(self.roles),
            "memberships": dict(self.memberships),
            "org_id": self.org_id,
            "disabled": self.disabled,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "oidc_client_id": self.oidc_client_id,
            "notes": self.notes or None,
            "kind": "agent",
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  roles TEXT NOT NULL,
  memberships TEXT NOT NULL DEFAULT '{}',
  org_id TEXT,
  disabled INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  created_by TEXT,
  oidc_client_id TEXT,
  notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS agents_org ON agents(org_id);
"""


def _clean_slug(slug: str) -> str:
    s = str(slug or "").strip().lower()
    if not _SLUG_RE.match(s):
        raise AgentStoreError("Agent slug must be 2-64 chars: lowercase letters, digits, ._-")
    if s in ("me", "new", "default", "system"):
        raise AgentStoreError(f"Agent slug '{s}' is reserved")
    return s


def _clean_roles(roles: list[str] | None) -> list[str]:
    out: list[str] = []
    for r in roles or ["builder"]:
        rr = str(r or "").strip().lower()
        if rr not in ROLE_NAMES:
            raise AgentStoreError(f"Unknown role '{r}' (allowed: {', '.join(ROLE_NAMES)})")
        if rr not in out:
            out.append(rr)
    if not out:
        out = ["builder"]
    return out


def _clean_memberships(raw: dict[str, str] | None) -> dict[str, str]:
    from app.core.trust.users import PROJECT_ROLES

    out: dict[str, str] = {}
    for proj, role in (raw or {}).items():
        p = str(proj or "").strip()
        rr = str(role or "").strip().lower()
        if not p:
            continue
        if rr not in PROJECT_ROLES:
            raise AgentStoreError(f"Unknown project role '{role}'")
        out[p] = rr
    return out


class AgentStore:
    def __init__(self, path: Path | str | None = None) -> None:
        from app.core.trust.users import default_store_path

        self.path = Path(path) if path is not None else default_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _from_row(self, row: sqlite3.Row) -> Agent:
        return Agent(
            id=row["id"],
            slug=row["slug"],
            name=row["name"],
            roles=json.loads(row["roles"] or "[]"),
            memberships=json.loads(row["memberships"] or "{}"),
            org_id=row["org_id"] or None,
            disabled=bool(row["disabled"]),
            created_at=row["created_at"],
            created_by=row["created_by"],
            oidc_client_id=row["oidc_client_id"] or None,
            notes=row["notes"] or "",
        )

    def list_agents(self, *, org_id: str | None = None, include_disabled: bool = False) -> list[Agent]:
        q = "SELECT * FROM agents WHERE 1=1"
        args: list[Any] = []
        if org_id:
            q += " AND org_id=?"
            args.append(org_id)
        if not include_disabled:
            q += " AND disabled=0"
        q += " ORDER BY slug"
        with self._conn() as c:
            return [self._from_row(r) for r in c.execute(q, args)]

    def get_agent(self, agent_id: str) -> Agent | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM agents WHERE id=? OR slug=?",
                (agent_id, str(agent_id or "").strip().lower()),
            ).fetchone()
            return self._from_row(row) if row else None

    def create_agent(
        self,
        slug: str,
        name: str = "",
        *,
        roles: list[str] | None = None,
        memberships: dict[str, str] | None = None,
        org_id: str | None = None,
        created_by: str | None = None,
        oidc_client_id: str | None = None,
        notes: str = "",
    ) -> Agent:
        clean = _clean_slug(slug)
        nm = str(name or "").strip()[:128] or clean
        rid = "agent_" + uuid.uuid4().hex[:12]
        roles_c = _clean_roles(roles)
        mem = _clean_memberships(memberships)
        oidc = (oidc_client_id or "").strip()[:128] or None
        with self._lock, self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO agents (id, slug, name, roles, memberships, org_id, disabled, created_at, created_by, oidc_client_id, notes)"
                    " VALUES (?,?,?,?,?,?,0,?,?,?,?)",
                    (
                        rid,
                        clean,
                        nm,
                        json.dumps(roles_c),
                        json.dumps(mem),
                        org_id,
                        time.time(),
                        created_by,
                        oidc,
                        str(notes or "")[:512],
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AgentStoreError(f"Agent slug '{clean}' already exists", 409, "conflict") from exc
        agent = self.get_agent(rid)
        assert agent is not None
        return agent

    def update_agent(
        self,
        agent_id: str,
        *,
        name: str | None = None,
        roles: list[str] | None = None,
        memberships: dict[str, str] | None = None,
        org_id: str | None = None,
        disabled: bool | None = None,
        oidc_client_id: str | None = None,
        notes: str | None = None,
        clear_oidc: bool = False,
    ) -> Agent:
        agent = self.get_agent(agent_id)
        if agent is None:
            raise AgentStoreError("Agent not found", 404, "not_found")
        sets: list[str] = []
        args: list[Any] = []
        if name is not None:
            sets.append("name=?")
            args.append(str(name).strip()[:128] or agent.name)
        if roles is not None:
            sets.append("roles=?")
            args.append(json.dumps(_clean_roles(roles)))
        if memberships is not None:
            sets.append("memberships=?")
            args.append(json.dumps(_clean_memberships(memberships)))
        if org_id is not None:
            sets.append("org_id=?")
            args.append(str(org_id).strip() or None)
        if disabled is not None:
            sets.append("disabled=?")
            args.append(1 if disabled else 0)
        if clear_oidc:
            sets.append("oidc_client_id=?")
            args.append(None)
        elif oidc_client_id is not None:
            sets.append("oidc_client_id=?")
            args.append(str(oidc_client_id).strip()[:128] or None)
        if notes is not None:
            sets.append("notes=?")
            args.append(str(notes)[:512])
        if not sets:
            return agent
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE agents SET {', '.join(sets)} WHERE id=?", (*args, agent.id))
        out = self.get_agent(agent.id)
        assert out is not None
        # P0: disabling an agent invalidates all minted gxa_ credentials immediately.
        if disabled is True:
            self.revoke_all_tokens(out.id)
        return out

    def mint_token(
        self,
        agent_id: str,
        *,
        name: str = "",
        ttl_s: float | None = None,
        created_by: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Issue ``gxa_…`` credential. Token shown once."""
        agent = self.get_agent(agent_id)
        if agent is None:
            raise AgentStoreError("Agent not found", 404, "not_found")
        if agent.disabled:
            raise AgentStoreError("Agent is disabled", 409, "disabled")
        store = get_user_store()
        token, cred = store.issue_credential(
            "agent",
            name=name or f"agent:{agent.slug}",
            ttl_s=ttl_s,
            created_by=created_by,
            meta={
                "agent_id": agent.id,
                "agent_slug": agent.slug,
                "org_id": agent.org_id,
            },
        )
        return token, {
            "credential_id": cred.id,
            "kind": cred.kind,
            "name": cred.name,
            "expires_at": cred.expires_at,
            "agent_id": agent.id,
            "agent_slug": agent.slug,
            "token": token,
        }

    def list_tokens(self, agent_id: str, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        agent = self.get_agent(agent_id)
        if agent is None:
            raise AgentStoreError("Agent not found", 404, "not_found")
        store = get_user_store()
        out = []
        for c in store.list_credentials(kind="agent", include_inactive=include_inactive):
            if (c.meta or {}).get("agent_id") != agent.id:
                continue
            out.append(c.public())
        return out

    def revoke_token(self, agent_id: str, credential_id: str) -> bool:
        agent = self.get_agent(agent_id)
        if agent is None:
            raise AgentStoreError("Agent not found", 404, "not_found")
        store = get_user_store()
        cred = store.get_credential(credential_id)
        if cred is None or cred.kind != "agent" or (cred.meta or {}).get("agent_id") != agent.id:
            raise AgentStoreError("Credential not found for this agent", 404, "not_found")
        return store.revoke_credential(credential_id)

    def revoke_all_tokens(self, agent_id: str) -> int:
        """Revoke every active agent credential bound to ``agent_id``."""
        agent = self.get_agent(agent_id)
        if agent is None:
            raise AgentStoreError("Agent not found", 404, "not_found")
        store = get_user_store()
        n = 0
        for cred in store.list_credentials(kind="agent", include_inactive=False):
            if (cred.meta or {}).get("agent_id") != agent.id:
                continue
            if store.revoke_credential(cred.id):
                n += 1
        return n


def get_agent_store() -> AgentStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = AgentStore()
        return _STORE


def reset_agent_store() -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = None


def identity_dict_for_agent(agent: Agent, *, credential_id: str | None = None) -> dict[str, Any]:
    """Build request identity for an agent principal (API + MCP + audit)."""
    return {
        "actor": f"agent:{agent.slug}",
        "actor_verified": True,
        "token_mapped": True,
        "claimed_actor": None,
        "kind": "agent",
        "agent_id": agent.id,
        "agent_slug": agent.slug,
        "worker_id": None,
        "user_id": None,
        "roles": list(agent.roles),
        "approver_roles": [],
        "memberships": dict(agent.memberships),
        "credential_id": credential_id,
        "auth_method": "agent_token",
        "org_id": agent.org_id,
        "oidc_client_id": agent.oidc_client_id,
    }


__all__ = [
    "AGENT_ROLES",
    "Agent",
    "AgentStore",
    "AgentStoreError",
    "get_agent_store",
    "identity_dict_for_agent",
    "reset_agent_store",
]
