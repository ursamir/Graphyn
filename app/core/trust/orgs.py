# app/core/trust/orgs.py
"""
Bounded Context:  BC6 — Observability & Storage (identity / access)
Responsibility:   Multi-tenant organizations: org records, membership roles,
                  project↔org mapping, active-org selection, and the one-time
                  migration that folds pre-tenancy data into a Default org.
Owns:             OrgStore, get_org_store(), reset_org_store(), Org,
                  OrgMembership, ORG_ROLES, DEFAULT_ORG_SLUG, DEFAULT_ORG_ID,
                  ensure_tenancy_migrated(), bind_org_to_identity(),
                  active_org_id(), org_project_names(), assign_project_org(),
                  OrgStoreError.
Public Surface:   The names above.
Must NOT:         Import app.api / app.domain / execution; return secrets.
Dependencies:     stdlib, app.core.trust.users (same SQLite path).
Reason To Change: Org schema, membership policy, or migration rules change.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ORG_ROLES: tuple[str, ...] = ("owner", "admin", "member", "viewer")
DEFAULT_ORG_SLUG = "default"
DEFAULT_ORG_ID = "org_default"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")

_STORE: "OrgStore | None" = None
_STORE_PATH: Path | None = None
_STORE_LOCK = threading.RLock()
_MIGRATED: set[str] = set()


class OrgStoreError(ValueError):
    def __init__(self, message: str, status_code: int = 400, code: str = "validation_failed") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass
class Org:
    id: str
    slug: str
    name: str
    created_at: float
    created_by: str | None
    disabled: bool = False
    region: str = ""  # data residency pin (e.g. us-east-1); empty = unset

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "created_at": _iso(self.created_at),
            "created_by": self.created_by,
            "disabled": self.disabled,
            "region": self.region or None,
            "is_default": self.id == DEFAULT_ORG_ID or self.slug == DEFAULT_ORG_SLUG,
        }


@dataclass
class OrgMembership:
    org_id: str
    user_id: str
    role: str
    added_at: float
    added_by: str | None = None
    username: str | None = None
    display_name: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "org_id": self.org_id,
            "user_id": self.user_id,
            "role": self.role,
            "added_at": _iso(self.added_at),
            "added_by": self.added_by,
            "username": self.username,
            "display_name": self.display_name or self.username,
        }


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _clean_role(role: str) -> str:
    r = str(role or "").strip().lower()
    if r not in ORG_ROLES:
        raise OrgStoreError(f"Unknown org role '{role}' (allowed: {', '.join(ORG_ROLES)})")
    return r


def _clean_slug(slug: str) -> str:
    s = str(slug or "").strip().lower()
    if not _SLUG_RE.match(s):
        raise OrgStoreError("Org slug must be 2-63 chars: lowercase letters, digits, hyphen")
    if s in ("new", "me", "default") and s != DEFAULT_ORG_SLUG:
        # 'default' reserved for the migrated org; block other reserved words for 'new'/'me'
        pass
    if s in ("new", "me"):
        raise OrgStoreError(f"Org slug '{s}' is reserved")
    return s


def _clean_region(region: str | None) -> str:
    """Normalize residency region tag; empty clears the pin."""
    s = str(region or "").strip().lower()
    if not s:
        return ""
    if len(s) > 64 or not re.match(r"^[a-z0-9][a-z0-9._-]{0,63}$", s):
        raise OrgStoreError(
            "Org region must be 1-64 chars: lowercase letters, digits, ._- "
            "(e.g. us-east-1, eu-west-1, ap-south-1)",
            400,
            "invalid_region",
        )
    return s


_SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (
  id TEXT PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  created_at REAL NOT NULL,
  created_by TEXT,
  disabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS org_memberships (
  org_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,
  added_at REAL NOT NULL,
  added_by TEXT,
  PRIMARY KEY (org_id, user_id)
);
CREATE INDEX IF NOT EXISTS org_memberships_user ON org_memberships(user_id);
CREATE TABLE IF NOT EXISTS org_projects (
  org_id TEXT NOT NULL,
  project TEXT NOT NULL,
  PRIMARY KEY (project)
);
CREATE INDEX IF NOT EXISTS org_projects_org ON org_projects(org_id);
"""


class OrgStore:
    """Organizations live in the same SQLite file as users (GRAPHYN_USERS_DB)."""

    def __init__(self, path: Path | str | None = None) -> None:
        from app.core.trust.users import default_store_path

        self.path = Path(path) if path is not None else default_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        self._lock = threading.RLock()
        with self._conn() as c:
            c.executescript(_SCHEMA)
            self._migrate_extras(c)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        ensure_tenancy_migrated(self)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _migrate_extras(self, c: sqlite3.Connection) -> None:
        # users.active_org_id
        user_cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
        if user_cols and "active_org_id" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN active_org_id TEXT")
        # join_tokens.org_id
        jt_cols = {r[1] for r in c.execute("PRAGMA table_info(join_tokens)")}
        if jt_cols and "org_id" not in jt_cols:
            c.execute("ALTER TABLE join_tokens ADD COLUMN org_id TEXT")
        # enrolled_workers.org_id
        ew_cols = {r[1] for r in c.execute("PRAGMA table_info(enrolled_workers)")}
        if ew_cols and "org_id" not in ew_cols:
            c.execute("ALTER TABLE enrolled_workers ADD COLUMN org_id TEXT")
        # orgs.region (data residency pin)
        org_cols = {r[1] for r in c.execute("PRAGMA table_info(orgs)")}
        if org_cols and "region" not in org_cols:
            c.execute("ALTER TABLE orgs ADD COLUMN region TEXT NOT NULL DEFAULT ''")

    def _org_from_row(self, row: sqlite3.Row) -> Org:
        keys = row.keys()
        return Org(
            id=row["id"],
            slug=row["slug"],
            name=row["name"],
            created_at=row["created_at"],
            created_by=row["created_by"],
            disabled=bool(row["disabled"]),
            region=str(row["region"] or "") if "region" in keys else "",
        )

    def list_orgs(self, *, include_disabled: bool = False) -> list[Org]:
        sql = "SELECT * FROM orgs"
        if not include_disabled:
            sql += " WHERE disabled=0"
        sql += " ORDER BY slug"
        with self._conn() as c:
            return [self._org_from_row(r) for r in c.execute(sql)]

    def get_org(self, org_id: str) -> Org | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM orgs WHERE id=?", (org_id,)).fetchone()
            return self._org_from_row(row) if row else None

    def get_org_by_slug(self, slug: str) -> Org | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM orgs WHERE slug=?", (str(slug or "").strip().lower(),)).fetchone()
            return self._org_from_row(row) if row else None

    def create_org(
        self,
        slug: str,
        name: str,
        *,
        owner_user_id: str,
        created_by: str | None = None,
        org_id: str | None = None,
        region: str | None = None,
    ) -> Org:
        clean = _clean_slug(slug)
        nm = str(name or "").strip()[:128] or clean
        oid = org_id or ("org_" + uuid.uuid4().hex[:12])
        reg = _clean_region(region)
        with self._lock, self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO orgs (id, slug, name, created_at, created_by, disabled, region) VALUES (?,?,?,?,?,0,?)",
                    (oid, clean, nm, time.time(), created_by, reg),
                )
            except sqlite3.IntegrityError as exc:
                raise OrgStoreError(f"Org slug '{clean}' already exists", 409, "conflict") from exc
            c.execute(
                "INSERT INTO org_memberships (org_id, user_id, role, added_at, added_by) VALUES (?,?,?,?,?)",
                (oid, owner_user_id, "owner", time.time(), created_by),
            )
            # Prefer new org as active if user has none.
            c.execute(
                "UPDATE users SET active_org_id=? WHERE id=? AND (active_org_id IS NULL OR active_org_id='')",
                (oid, owner_user_id),
            )
        org = self.get_org(oid)
        assert org is not None
        return org

    def update_org(
        self,
        org_id: str,
        *,
        name: str | None = None,
        disabled: bool | None = None,
        region: str | None = None,
    ) -> Org:
        org = self.get_org(org_id)
        if org is None:
            raise OrgStoreError("Org not found", 404, "not_found")
        if org.id == DEFAULT_ORG_ID or org.slug == DEFAULT_ORG_SLUG:
            if disabled is True:
                raise OrgStoreError("Cannot disable the default org", 409, "conflict")
        sets: list[str] = []
        args: list[Any] = []
        if name is not None:
            sets.append("name=?")
            args.append(str(name).strip()[:128] or org.name)
        if disabled is not None:
            sets.append("disabled=?")
            args.append(1 if disabled else 0)
        if region is not None:
            sets.append("region=?")
            args.append(_clean_region(region))
        if not sets:
            return org
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE orgs SET {', '.join(sets)} WHERE id=?", (*args, org_id))
        out = self.get_org(org_id)
        assert out is not None
        return out

    def set_membership(self, org_id: str, user_id: str, role: str, *, added_by: str | None = None) -> None:
        if self.get_org(org_id) is None:
            raise OrgStoreError("Org not found", 404, "not_found")
        r = _clean_role(role)
        with self._lock, self._conn() as c:
            user = c.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
            if user is None:
                raise OrgStoreError("User not found", 404, "not_found")
            # Last-owner protection
            if r != "owner":
                owners = [
                    row["user_id"]
                    for row in c.execute(
                        "SELECT user_id FROM org_memberships WHERE org_id=? AND role='owner'",
                        (org_id,),
                    )
                ]
                if len(owners) == 1 and owners[0] == user_id:
                    raise OrgStoreError("Cannot demote the last org owner", 409, "conflict")
            c.execute(
                "INSERT INTO org_memberships (org_id, user_id, role, added_at, added_by) VALUES (?,?,?,?,?)"
                " ON CONFLICT(org_id, user_id) DO UPDATE SET role=excluded.role",
                (org_id, user_id, r, time.time(), added_by),
            )

    def remove_membership(self, org_id: str, user_id: str) -> bool:
        with self._lock, self._conn() as c:
            owners = [
                row["user_id"]
                for row in c.execute(
                    "SELECT user_id FROM org_memberships WHERE org_id=? AND role='owner'",
                    (org_id,),
                )
            ]
            if len(owners) == 1 and owners[0] == user_id:
                raise OrgStoreError("Cannot remove the last org owner", 409, "conflict")
            return c.execute(
                "DELETE FROM org_memberships WHERE org_id=? AND user_id=?",
                (org_id, user_id),
            ).rowcount > 0

    def org_members(self, org_id: str) -> list[OrgMembership]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT m.*, u.username, u.display_name FROM org_memberships m"
                " LEFT JOIN users u ON u.id = m.user_id WHERE m.org_id=? ORDER BY u.username",
                (org_id,),
            ).fetchall()
        return [
            OrgMembership(
                org_id=r["org_id"],
                user_id=r["user_id"],
                role=r["role"],
                added_at=r["added_at"],
                added_by=r["added_by"],
                username=r["username"],
                display_name=r["display_name"],
            )
            for r in rows
        ]

    def membership_for(self, org_id: str, user_id: str) -> OrgMembership | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT m.*, u.username, u.display_name FROM org_memberships m"
                " LEFT JOIN users u ON u.id = m.user_id WHERE m.org_id=? AND m.user_id=?",
                (org_id, user_id),
            ).fetchone()
        if not r:
            return None
        return OrgMembership(
            org_id=r["org_id"],
            user_id=r["user_id"],
            role=r["role"],
            added_at=r["added_at"],
            added_by=r["added_by"],
            username=r["username"],
            display_name=r["display_name"],
        )

    def orgs_for_user(self, user_id: str) -> list[tuple[Org, str]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT o.*, m.role FROM orgs o JOIN org_memberships m ON m.org_id=o.id"
                " WHERE m.user_id=? AND o.disabled=0 ORDER BY o.slug",
                (user_id,),
            ).fetchall()
        return [(self._org_from_row(r), r["role"]) for r in rows]

    def get_user_active_org_id(self, user_id: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT active_org_id FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            return None
        return row["active_org_id"] or None

    def set_user_active_org(self, user_id: str, org_id: str) -> None:
        mem = self.membership_for(org_id, user_id)
        if mem is None:
            raise OrgStoreError("Not a member of that organization", 403, "forbidden")
        org = self.get_org(org_id)
        if org is None or org.disabled:
            raise OrgStoreError("Org not found", 404, "not_found")
        with self._lock, self._conn() as c:
            c.execute("UPDATE users SET active_org_id=? WHERE id=?", (org_id, user_id))

    def assign_project(self, project: str, org_id: str) -> None:
        pname = str(project or "").strip()
        if not pname:
            raise OrgStoreError("project is required")
        if self.get_org(org_id) is None:
            raise OrgStoreError("Org not found", 404, "not_found")
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO org_projects (org_id, project) VALUES (?,?)"
                " ON CONFLICT(project) DO UPDATE SET org_id=excluded.org_id",
                (org_id, pname),
            )

    def project_org_id(self, project: str) -> str | None:
        pname = str(project or "").strip()
        if not pname:
            return None
        with self._conn() as c:
            row = c.execute("SELECT org_id FROM org_projects WHERE project=?", (pname,)).fetchone()
        if row:
            return row["org_id"]
        # Legacy / unmapped projects belong to the default org.
        return DEFAULT_ORG_ID

    def projects_in_org(self, org_id: str) -> set[str]:
        with self._conn() as c:
            mapped = {r["project"] for r in c.execute("SELECT project FROM org_projects WHERE org_id=?", (org_id,))}
            all_mapped = {r["project"] for r in c.execute("SELECT project FROM org_projects")}
        if org_id == DEFAULT_ORG_ID:
            try:
                from app.domain.project_manager import ProjectManager

                on_disk = {str(p.get("name") or "") for p in ProjectManager().list_all() if p.get("name")}
                mapped |= on_disk - all_mapped
            except Exception:
                pass
        return mapped

    def ensure_default_org(self) -> Org:
        existing = self.get_org(DEFAULT_ORG_ID) or self.get_org_by_slug(DEFAULT_ORG_SLUG)
        if existing:
            return existing
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO orgs (id, slug, name, created_at, created_by, disabled) VALUES (?,?,?,?,?,0)",
                (DEFAULT_ORG_ID, DEFAULT_ORG_SLUG, "Default", time.time(), "migration"),
            )
        org = self.get_org(DEFAULT_ORG_ID)
        assert org is not None
        return org


def ensure_tenancy_migrated(store: OrgStore | None = None) -> Org:
    """Idempotent: default org + backfill users/projects into it.

    Safe to call repeatedly: new users created after the first migration are
    still enrolled into the default org when this runs again.
    """
    store = store or get_org_store()
    key = str(store.path.resolve())
    with store._lock:
        org = store.ensure_default_org()
        with store._conn() as c:
            for u in c.execute("SELECT id, roles FROM users"):
                exists = c.execute(
                    "SELECT 1 FROM org_memberships WHERE org_id=? AND user_id=?",
                    (org.id, u["id"]),
                ).fetchone()
                if exists:
                    continue
                roles = json.loads(u["roles"] or "[]")
                role = "owner" if "admin" in roles else "member"
                c.execute(
                    "INSERT INTO org_memberships (org_id, user_id, role, added_at, added_by) VALUES (?,?,?,?,?)",
                    (org.id, u["id"], role, time.time(), "migration"),
                )
            c.execute(
                "UPDATE users SET active_org_id=? WHERE active_org_id IS NULL OR active_org_id=''",
                (org.id,),
            )
        if key not in _MIGRATED:
            try:
                from app.domain.project_manager import ProjectManager

                for p in ProjectManager().list_all():
                    name = str((p or {}).get("name") or "").strip()
                    if not name:
                        continue
                    with store._conn() as c:
                        row = c.execute("SELECT 1 FROM org_projects WHERE project=?", (name,)).fetchone()
                    if row is None:
                        store.assign_project(name, org.id)
            except Exception:
                pass
            try:
                _migrate_credentials_org(org.id)
            except Exception:
                pass
            _MIGRATED.add(key)
        return org


def _migrate_credentials_org(org_id: str) -> None:
    from app.core.credentials.crypto import credentials_dir

    path = credentials_dir() / "store.sqlite"
    if not path.is_file():
        return
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(connections)")}
        if "org_id" not in cols:
            conn.execute("ALTER TABLE connections ADD COLUMN org_id TEXT")
        conn.execute(
            "UPDATE connections SET org_id=? WHERE org_id IS NULL OR org_id=''",
            (org_id,),
        )
    finally:
        conn.close()


def bind_org_to_identity(ident: dict[str, Any] | None, *, header_org_id: str | None = None) -> dict[str, Any] | None:
    """Attach ``org_id`` / ``org_role`` / ``orgs`` for user identities."""
    if not ident or ident.get("kind") != "user":
        return ident
    store = get_org_store()
    ensure_tenancy_migrated(store)
    uid = str(ident.get("user_id") or "")
    memberships = store.orgs_for_user(uid)
    org_list = [{"id": o.id, "slug": o.slug, "name": o.name, "role": role} for o, role in memberships]
    ident["orgs"] = org_list
    chosen = None
    hdr = (header_org_id or "").strip()
    if hdr:
        for o, role in memberships:
            if o.id == hdr or o.slug == hdr:
                chosen = (o.id, role)
                break
    if chosen is None:
        pref = store.get_user_active_org_id(uid)
        if pref:
            for o, role in memberships:
                if o.id == pref:
                    chosen = (o.id, role)
                    break
    if chosen is None and memberships:
        # Prefer default org when present.
        for o, role in memberships:
            if o.id == DEFAULT_ORG_ID or o.slug == DEFAULT_ORG_SLUG:
                chosen = (o.id, role)
                break
        if chosen is None:
            chosen = (memberships[0][0].id, memberships[0][1])
    if chosen:
        ident["org_id"] = chosen[0]
        ident["org_role"] = chosen[1]
    else:
        ident["org_id"] = None
        ident["org_role"] = None
    return ident


def active_org_id(ident: dict[str, Any] | None) -> str | None:
    if not ident:
        return None
    return ident.get("org_id")


def org_can_see_all_projects(org_role: str | None) -> bool:
    return str(org_role or "") in ("owner", "admin")


def get_org_store() -> OrgStore:
    global _STORE, _STORE_PATH
    from app.core.trust.users import default_store_path

    path = default_store_path()
    with _STORE_LOCK:
        if _STORE is None or _STORE_PATH != path:
            _STORE = OrgStore(path)
            _STORE_PATH = path
        return _STORE


def reset_org_store() -> None:
    global _STORE, _STORE_PATH
    with _STORE_LOCK:
        _STORE = None
        _STORE_PATH = None
        _MIGRATED.clear()


__all__ = [
    "DEFAULT_ORG_ID",
    "DEFAULT_ORG_SLUG",
    "ORG_ROLES",
    "Org",
    "OrgMembership",
    "OrgStore",
    "OrgStoreError",
    "active_org_id",
    "bind_org_to_identity",
    "ensure_tenancy_migrated",
    "get_org_store",
    "org_can_see_all_projects",
    "reset_org_store",
]
