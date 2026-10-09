# app/core/trust/users.py
"""
Bounded Context:  BC6 — Observability & Storage (identity / access)
Responsibility:   Durable store for platform users, their credentials
                  (session + personal API tokens + worker credentials), project
                  memberships and Mode B worker join tokens. Passwords are
                  scrypt-hashed; tokens are opaque ``gx<kind>_<id>_<secret>``
                  strings stored only as sha256(secret) so every request can
                  name the exact credential it used (audit lineage).
Owns:             UserStore, get_user_store(), reset_user_store(), User,
                  Credential, JoinToken, ROLE_NAMES, hash_password(),
                  verify_password(), parse_token(), UserStoreError.
Public Surface:   get_user_store() and the dataclasses above.
Must NOT:         Import app.api / app.domain / execution; return or log
                  password hashes, token secrets or token hashes.
Dependencies:     stdlib (sqlite3, hashlib, hmac, secrets, threading, json),
                  app.core.config.graphyn_home.
Reason To Change: User / credential / membership / join-token schema changes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROLE_NAMES: tuple[str, ...] = ("admin", "operator", "builder", "approver", "auditor", "viewer")
PROJECT_ROLES: tuple[str, ...] = ("owner", "builder", "approver", "viewer")
CREDENTIAL_KINDS: tuple[str, ...] = ("session", "api", "worker", "agent")

_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_TOKEN_RE = re.compile(r"^gx(?P<kind>[suwja])_(?P<id>[a-f0-9]{16})_(?P<secret>[A-Za-z0-9_-]{32,})$")
_KIND_PREFIX = {"session": "s", "api": "u", "worker": "w", "join": "j", "agent": "a"}
_PREFIX_KIND = {v: k for k, v in _KIND_PREFIX.items()}

SESSION_TTL_S = 12 * 3600
WORKER_CREDENTIAL_TTL_S = 24 * 3600
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
MIN_PASSWORD_LEN = 10


class UserStoreError(ValueError):
    """Validation / conflict error with an HTTP-ish status code."""

    def __init__(self, message: str, status_code: int = 400, code: str = "validation_failed") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


# ── hashing ────────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    if len(password or "") < MIN_PASSWORD_LEN:
        raise UserStoreError(f"Password must be at least {MIN_PASSWORD_LEN} characters")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, dk_hex = str(stored or "").split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            (password or "").encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(dk_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), dk_hex)


def _secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def parse_token(token: str | None) -> tuple[str, str, str] | None:
    """``(kind, id, secret)`` for a Graphyn-issued token, else None."""
    m = _TOKEN_RE.match(str(token or "").strip())
    if not m:
        return None
    return _PREFIX_KIND[m.group("kind")], m.group("id"), m.group("secret")


def looks_like_issued_token(token: str | None) -> bool:
    return parse_token(token) is not None


def _new_token(kind: str) -> tuple[str, str, str]:
    tid = uuid.uuid4().hex[:16]
    secret = secrets.token_urlsafe(32)
    return tid, secret, f"gx{_KIND_PREFIX[kind]}_{tid}_{secret}"


# ── records ────────────────────────────────────────────────────────────────────


@dataclass
class User:
    id: str
    username: str
    display_name: str
    roles: list[str]
    approver_roles: list[str]
    disabled: bool
    created_at: float
    created_by: str | None
    last_login_at: float | None
    memberships: dict[str, str] = field(default_factory=dict)
    email: str | None = None
    oidc_issuer: str | None = None
    oidc_sub: str | None = None
    has_password: bool = True

    def public(self) -> dict[str, Any]:
        auth_provider = "oidc" if self.oidc_sub else "local"
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "roles": list(self.roles),
            "approver_roles": list(self.approver_roles),
            "disabled": self.disabled,
            "created_at": _iso(self.created_at),
            "created_by": self.created_by,
            "last_login_at": _iso(self.last_login_at),
            "memberships": dict(self.memberships),
            "email": self.email,
            "auth_provider": auth_provider,
            "has_password": bool(self.has_password),
        }


@dataclass
class Credential:
    id: str
    kind: str
    user_id: str | None
    worker_id: str | None
    name: str
    created_at: float
    expires_at: float | None
    last_used_at: float | None
    revoked_at: float | None
    created_by: str | None
    meta: dict[str, Any]

    @property
    def active(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > time.time()

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "user_id": self.user_id,
            "worker_id": self.worker_id,
            "name": self.name,
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at),
            "last_used_at": _iso(self.last_used_at),
            "revoked_at": _iso(self.revoked_at),
            "created_by": self.created_by,
            "active": self.active,
            "meta": dict(self.meta),
        }


@dataclass
class JoinToken:
    id: str
    pool: str | None
    labels: list[str]
    allowed_plugins: list[str] | None
    max_uses: int
    uses: int
    created_at: float
    expires_at: float
    revoked_at: float | None
    created_by: str | None
    note: str
    workers: list[str]
    org_id: str | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None and self.expires_at > time.time() and self.uses < self.max_uses

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pool": self.pool,
            "labels": list(self.labels),
            "allowed_plugins": self.allowed_plugins,
            "max_uses": self.max_uses,
            "uses": self.uses,
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at),
            "revoked_at": _iso(self.revoked_at),
            "created_by": self.created_by,
            "note": self.note,
            "workers": list(self.workers),
            "active": self.active,
            "org_id": self.org_id,
        }


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _clean_roles(roles: Iterable[str] | None, allowed: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for r in roles or []:
        s = str(r or "").strip().lower()
        if not s:
            continue
        if s not in allowed:
            raise UserStoreError(f"Unknown role '{s}' (allowed: {', '.join(allowed)})")
        if s not in out:
            out.append(s)
    return out


def _clean_labels(values: Iterable[str] | None, what: str) -> list[str]:
    out: list[str] = []
    for v in values or []:
        s = str(v or "").strip()
        if not s:
            continue
        if not _LABEL_RE.match(s):
            raise UserStoreError(f"Invalid {what} '{s}'")
        if s not in out:
            out.append(s)
    return out


# ── store ──────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  password_hash TEXT,
  roles TEXT NOT NULL DEFAULT '[]',
  approver_roles TEXT NOT NULL DEFAULT '[]',
  disabled INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  created_by TEXT,
  last_login_at REAL
);
CREATE TABLE IF NOT EXISTS credentials (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  user_id TEXT,
  worker_id TEXT,
  name TEXT NOT NULL DEFAULT '',
  secret_hash TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL,
  last_used_at REAL,
  revoked_at REAL,
  created_by TEXT,
  meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS credentials_user ON credentials(user_id);
CREATE INDEX IF NOT EXISTS credentials_worker ON credentials(worker_id);
CREATE TABLE IF NOT EXISTS memberships (
  project TEXT NOT NULL,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,
  added_at REAL NOT NULL,
  added_by TEXT,
  PRIMARY KEY (project, user_id)
);
CREATE TABLE IF NOT EXISTS join_tokens (
  id TEXT PRIMARY KEY,
  secret_hash TEXT NOT NULL,
  pool TEXT,
  labels TEXT NOT NULL DEFAULT '[]',
  allowed_plugins TEXT,
  max_uses INTEGER NOT NULL DEFAULT 1,
  uses INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  revoked_at REAL,
  created_by TEXT,
  note TEXT NOT NULL DEFAULT '',
  workers TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS enrolled_workers (
  worker_id TEXT PRIMARY KEY,
  join_token_id TEXT,
  pool TEXT,
  labels TEXT NOT NULL DEFAULT '[]',
  allowed_plugins TEXT,
  hostname TEXT NOT NULL DEFAULT '',
  cert_fingerprint TEXT,
  cert_expires_at REAL,
  enrolled_at REAL NOT NULL,
  enrolled_by TEXT,
  revoked_at REAL,
  revoked_by TEXT
);
"""

_LAST_USED_GRANULARITY_S = 60.0


def default_store_path() -> Path:
    override = (os.environ.get("GRAPHYN_USERS_DB") or "").strip()
    if override:
        return Path(override).expanduser()
    from app.core.config import graphyn_home

    return graphyn_home() / "auth" / "users.db"


class UserStore:
    """sqlite-backed users / credentials / memberships / join tokens.

    One connection per call (sqlite handles cross-process locking); a process
    lock serialises writers so read-modify-write sequences (join-token use
    counts, last admin checks) are atomic within the control plane.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        self._lock = threading.RLock()
        with self._conn() as c:
            c.executescript(_SCHEMA)
            self._migrate_schema(c)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    # ── users ──────────────────────────────────────────────────────────────

    def _migrate_schema(self, c: sqlite3.Connection) -> None:
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
        if "email" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if "oidc_issuer" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN oidc_issuer TEXT")
        if "oidc_sub" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN oidc_sub TEXT")
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS users_oidc_sub ON users(oidc_issuer, oidc_sub)"
            " WHERE oidc_sub IS NOT NULL AND oidc_issuer IS NOT NULL"
        )

    def _row_get(self, row: sqlite3.Row, key: str, default: Any = None) -> Any:
        try:
            return row[key]
        except (IndexError, KeyError):
            return default

    def _user_from_row(self, row: sqlite3.Row, c: sqlite3.Connection) -> User:
        mem = {r["project"]: r["role"] for r in c.execute("SELECT project, role FROM memberships WHERE user_id=?", (row["id"],))}
        pw = self._row_get(row, "password_hash")
        return User(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"] or row["username"],
            roles=json.loads(row["roles"] or "[]"),
            approver_roles=json.loads(row["approver_roles"] or "[]"),
            disabled=bool(row["disabled"]),
            created_at=row["created_at"],
            created_by=row["created_by"],
            last_login_at=row["last_login_at"],
            memberships=mem,
            email=(self._row_get(row, "email") or None) or None,
            oidc_issuer=(self._row_get(row, "oidc_issuer") or None) or None,
            oidc_sub=(self._row_get(row, "oidc_sub") or None) or None,
            has_password=bool(pw),
        )

    def has_users(self) -> bool:
        # Users are never deleted (only disabled), so a positive answer is sticky.
        if getattr(self, "_has_users", False):
            return True
        with self._conn() as c:
            found = c.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
        if found:
            self._has_users = True
        return found

    def list_users(self) -> list[User]:
        with self._conn() as c:
            return [self._user_from_row(r, c) for r in c.execute("SELECT * FROM users ORDER BY username")]

    def get_user(self, user_id: str) -> User | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            return self._user_from_row(row, c) if row else None

    def get_user_by_username(self, username: str) -> User | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE username=?", (str(username or "").strip().lower(),)).fetchone()
            return self._user_from_row(row, c) if row else None

    def create_user(
        self,
        username: str,
        password: str,
        *,
        roles: Iterable[str] = ("viewer",),
        display_name: str = "",
        approver_roles: Iterable[str] = (),
        created_by: str | None = None,
    ) -> User:
        uname = str(username or "").strip().lower()
        if not _USERNAME_RE.match(uname):
            raise UserStoreError("Username must be 2-64 chars: lowercase letters, digits, '.', '_' or '-'")
        role_list = _clean_roles(roles, ROLE_NAMES) or ["viewer"]
        appr = _clean_labels(approver_roles, "approver role")
        pw_hash = hash_password(password)
        uid = "u_" + uuid.uuid4().hex[:12]
        with self._lock, self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO users (id, username, display_name, password_hash, roles, approver_roles, created_at, created_by)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (uid, uname, str(display_name or "").strip()[:128], pw_hash, json.dumps(role_list), json.dumps(appr), time.time(), created_by),
                )
            except sqlite3.IntegrityError:
                raise UserStoreError(f"User '{uname}' already exists", 409, "conflict")
        user = self.get_user(uid)
        assert user is not None
        try:
            from app.core.trust.orgs import DEFAULT_ORG_ID, ensure_tenancy_migrated, get_org_store

            ensure_tenancy_migrated(get_org_store())
            role = "owner" if "admin" in (user.roles or []) else "member"
            get_org_store().set_membership(DEFAULT_ORG_ID, user.id, role, added_by=created_by or "user.create")
            if not get_org_store().get_user_active_org_id(user.id):
                get_org_store().set_user_active_org(user.id, DEFAULT_ORG_ID)
        except Exception:
            pass
        return user

    def _active_admin_ids(self, c: sqlite3.Connection) -> set[str]:
        out = set()
        for r in c.execute("SELECT id, roles FROM users WHERE disabled=0"):
            if "admin" in json.loads(r["roles"] or "[]"):
                out.add(r["id"])
        return out

    def update_user(
        self,
        user_id: str,
        *,
        roles: Iterable[str] | None = None,
        display_name: str | None = None,
        approver_roles: Iterable[str] | None = None,
        disabled: bool | None = None,
        password: str | None = None,
    ) -> User:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None:
                raise UserStoreError("User not found", 404, "not_found")
            sets: list[str] = []
            args: list[Any] = []
            new_roles = None
            if roles is not None:
                new_roles = _clean_roles(roles, ROLE_NAMES) or ["viewer"]
                sets.append("roles=?")
                args.append(json.dumps(new_roles))
            if display_name is not None:
                sets.append("display_name=?")
                args.append(str(display_name).strip()[:128])
            if approver_roles is not None:
                sets.append("approver_roles=?")
                args.append(json.dumps(_clean_labels(approver_roles, "approver role")))
            if disabled is not None:
                sets.append("disabled=?")
                args.append(1 if disabled else 0)
            if password is not None:
                sets.append("password_hash=?")
                args.append(hash_password(password))
            admins = self._active_admin_ids(c)
            losing_admin = user_id in admins and (
                (new_roles is not None and "admin" not in new_roles) or disabled is True
            )
            if losing_admin and len(admins) <= 1:
                raise UserStoreError("Cannot remove the last active admin", 409, "conflict")
            if sets:
                c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", (*args, user_id))
            if disabled or password is not None:
                # Disabling / resetting a password ends every live session and token.
                kinds = ("session", "api") if disabled else ("session",)
                c.execute(
                    f"UPDATE credentials SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND kind IN ({','.join('?' * len(kinds))})",
                    (time.time(), user_id, *kinds),
                )
        user = self.get_user(user_id)
        assert user is not None
        return user

    def authenticate(self, username: str, password: str) -> User | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE username=?", (str(username or "").strip().lower(),)).fetchone()
            if row is None:
                verify_password(password, hash_password("x" * MIN_PASSWORD_LEN))  # equalise timing
                return None
            pw_hash = row["password_hash"] or ""
            if row["disabled"] or not pw_hash or not verify_password(password, pw_hash):
                return None
            c.execute("UPDATE users SET last_login_at=? WHERE id=?", (time.time(), row["id"]))
            return self._user_from_row(row, c)

    def get_user_by_oidc(self, issuer: str, sub: str) -> User | None:
        iss = str(issuer or "").strip().rstrip("/")
        sid = str(sub or "").strip()
        if not iss or not sid:
            return None
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM users WHERE oidc_issuer=? AND oidc_sub=?",
                (iss, sid),
            ).fetchone()
            return self._user_from_row(row, c) if row else None

    def upsert_oidc_user(
        self,
        *,
        issuer: str,
        sub: str,
        username: str,
        display_name: str = "",
        email: str = "",
        default_roles: Iterable[str] = ("viewer",),
        auto_provision: bool = True,
    ) -> User:
        """Find or create a user bound to an OIDC subject.

        First user on an empty store becomes admin (bootstrap). Username
        collisions with a different unbound local account are refused.
        """
        iss = str(issuer or "").strip().rstrip("/")
        sid = str(sub or "").strip()
        if not iss or not sid:
            raise UserStoreError("OIDC issuer and sub are required", 400, "validation_failed")
        existing = self.get_user_by_oidc(iss, sid)
        if existing is not None:
            if existing.disabled:
                raise UserStoreError("Account disabled", 403, "disabled")
            with self._lock, self._conn() as c:
                c.execute(
                    "UPDATE users SET last_login_at=?, display_name=COALESCE(NULLIF(?, ''), display_name),"
                    " email=COALESCE(NULLIF(?, ''), email) WHERE id=?",
                    (time.time(), str(display_name or "").strip()[:128], str(email or "").strip()[:256], existing.id),
                )
            user = self.get_user(existing.id)
            assert user is not None
            return user

        uname = str(username or "").strip().lower()
        if not _USERNAME_RE.match(uname):
            raise UserStoreError("OIDC username is not a valid Graphyn username", 400, "validation_failed")
        by_name = self.get_user_by_username(uname)
        if by_name is not None:
            if by_name.oidc_sub and (by_name.oidc_issuer != iss or by_name.oidc_sub != sid):
                raise UserStoreError(
                    f"Username '{uname}' is already linked to another identity provider account",
                    409,
                    "conflict",
                )
            if by_name.oidc_sub is None and by_name.has_password:
                # Link local account to this OIDC subject (same username).
                if by_name.disabled:
                    raise UserStoreError("Account disabled", 403, "disabled")
                with self._lock, self._conn() as c:
                    c.execute(
                        "UPDATE users SET oidc_issuer=?, oidc_sub=?, email=COALESCE(NULLIF(?, ''), email),"
                        " display_name=COALESCE(NULLIF(?, ''), display_name), last_login_at=? WHERE id=?",
                        (iss, sid, str(email or "").strip()[:256], str(display_name or "").strip()[:128], time.time(), by_name.id),
                    )
                user = self.get_user(by_name.id)
                assert user is not None
                return user
            raise UserStoreError(f"Username '{uname}' already exists", 409, "conflict")

        if not auto_provision:
            raise UserStoreError(
                "No Graphyn account is linked to this SSO identity — ask an admin to create one",
                403,
                "not_provisioned",
            )

        # First human on an empty store is admin so OIDC-only deploys can bootstrap.
        if not self.has_users():
            role_list = ["admin"]
        else:
            role_list = _clean_roles(default_roles, ROLE_NAMES) or ["viewer"]

        # Username taken mid-flight: append short subject hash.
        candidate = uname
        for _ in range(6):
            if self.get_user_by_username(candidate) is None:
                break
            suffix = hashlib.sha256(f"{iss}:{sid}".encode()).hexdigest()[:6]
            candidate = f"{uname[:57]}-{suffix}"[:64]
        else:
            raise UserStoreError("Could not allocate a unique username for SSO user", 409, "conflict")

        uid = "u_" + uuid.uuid4().hex[:12]
        with self._lock, self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO users (id, username, display_name, password_hash, roles, approver_roles,"
                    " created_at, created_by, email, oidc_issuer, oidc_sub, last_login_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        uid,
                        candidate,
                        str(display_name or "").strip()[:128] or candidate,
                        None,
                        json.dumps(role_list),
                        json.dumps([]),
                        time.time(),
                        f"oidc:{iss}",
                        str(email or "").strip()[:256] or None,
                        iss,
                        sid,
                        time.time(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise UserStoreError("OIDC user conflict", 409, "conflict") from exc
        self._has_users = True
        user = self.get_user(uid)
        assert user is not None
        try:
            from app.core.trust.orgs import DEFAULT_ORG_ID, ensure_tenancy_migrated, get_org_store

            ensure_tenancy_migrated(get_org_store())
            role = "owner" if "admin" in (user.roles or []) else "member"
            get_org_store().set_membership(DEFAULT_ORG_ID, user.id, role, added_by=f"oidc:{iss}")
            get_org_store().set_user_active_org(user.id, DEFAULT_ORG_ID)
        except Exception:
            pass
        return user

    # ── memberships ────────────────────────────────────────────────────────

    def set_membership(self, project: str, user_id: str, role: str, *, added_by: str | None = None) -> None:
        r = _clean_roles([role], PROJECT_ROLES)
        if not r:
            raise UserStoreError("role is required")
        if self.get_user(user_id) is None:
            raise UserStoreError("User not found", 404, "not_found")
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO memberships (project, user_id, role, added_at, added_by) VALUES (?,?,?,?,?)"
                " ON CONFLICT(project, user_id) DO UPDATE SET role=excluded.role",
                (project, user_id, r[0], time.time(), added_by),
            )

    def remove_membership(self, project: str, user_id: str) -> bool:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM memberships WHERE project=? AND user_id=?", (project, user_id)).rowcount > 0

    def project_members(self, project: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT m.user_id, m.role, m.added_at, m.added_by, u.username, u.display_name FROM memberships m"
                " JOIN users u ON u.id = m.user_id WHERE m.project=? ORDER BY u.username",
                (project,),
            ).fetchall()
        return [
            {
                "user_id": r["user_id"],
                "username": r["username"],
                "display_name": r["display_name"] or r["username"],
                "role": r["role"],
                "added_at": _iso(r["added_at"]),
                "added_by": r["added_by"],
            }
            for r in rows
        ]

    # ── credentials ────────────────────────────────────────────────────────

    def _cred_from_row(self, r: sqlite3.Row) -> Credential:
        return Credential(
            id=r["id"],
            kind=r["kind"],
            user_id=r["user_id"],
            worker_id=r["worker_id"],
            name=r["name"],
            created_at=r["created_at"],
            expires_at=r["expires_at"],
            last_used_at=r["last_used_at"],
            revoked_at=r["revoked_at"],
            created_by=r["created_by"],
            meta=json.loads(r["meta"] or "{}"),
        )

    def issue_credential(
        self,
        kind: str,
        *,
        user_id: str | None = None,
        worker_id: str | None = None,
        name: str = "",
        ttl_s: float | None = None,
        created_by: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> tuple[str, Credential]:
        """Return ``(token, credential)``. The token is shown once and never stored."""
        if kind not in CREDENTIAL_KINDS:
            raise UserStoreError(f"Unknown credential kind '{kind}'")
        if kind in ("session", "api") and not user_id:
            raise UserStoreError("user_id is required")
        if kind == "worker" and not worker_id:
            raise UserStoreError("worker_id is required")
        if kind == "agent":
            aid = (meta or {}).get("agent_id") if meta else None
            if not aid:
                raise UserStoreError("meta.agent_id is required for agent credentials")
        tid, secret, token = _new_token(kind)
        now = time.time()
        expires = now + float(ttl_s) if ttl_s else None
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO credentials (id, kind, user_id, worker_id, name, secret_hash, created_at, expires_at, created_by, meta)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tid, kind, user_id, worker_id, str(name or "").strip()[:128], _secret_hash(secret), now, expires, created_by, json.dumps(meta or {})),
            )
            row = c.execute("SELECT * FROM credentials WHERE id=?", (tid,)).fetchone()
        return token, self._cred_from_row(row)

    def resolve_token(self, token: str | None) -> tuple[Credential, User | None] | None:
        """Active credential (+ owning enabled user) for an issued token, else None."""
        parsed = parse_token(token)
        if parsed is None:
            return None
        kind, tid, secret = parsed
        if kind == "join":
            return None
        with self._conn() as c:
            row = c.execute("SELECT * FROM credentials WHERE id=?", (tid,)).fetchone()
            if row is None or row["kind"] != kind:
                return None
            if not hmac.compare_digest(row["secret_hash"], _secret_hash(secret)):
                return None
            cred = self._cred_from_row(row)
            if not cred.active:
                return None
            user = None
            if cred.user_id:
                urow = c.execute("SELECT * FROM users WHERE id=?", (cred.user_id,)).fetchone()
                if urow is None or urow["disabled"]:
                    return None
                user = self._user_from_row(urow, c)
            now = time.time()
            if cred.last_used_at is None or now - cred.last_used_at > _LAST_USED_GRANULARITY_S:
                c.execute("UPDATE credentials SET last_used_at=? WHERE id=?", (now, tid))
        return cred, user

    def get_credential(self, cred_id: str) -> Credential | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM credentials WHERE id=?", (cred_id,)).fetchone()
            return self._cred_from_row(row) if row else None

    def list_credentials(
        self,
        *,
        user_id: str | None = None,
        worker_id: str | None = None,
        kind: str | None = None,
        include_inactive: bool = False,
    ) -> list[Credential]:
        q = "SELECT * FROM credentials WHERE 1=1"
        args: list[Any] = []
        if user_id is not None:
            q += " AND user_id=?"
            args.append(user_id)
        if worker_id is not None:
            q += " AND worker_id=?"
            args.append(worker_id)
        if kind is not None:
            q += " AND kind=?"
            args.append(kind)
        q += " ORDER BY created_at DESC"
        with self._conn() as c:
            creds = [self._cred_from_row(r) for r in c.execute(q, args)]
        return creds if include_inactive else [x for x in creds if x.active]

    def revoke_credential(self, cred_id: str) -> bool:
        with self._lock, self._conn() as c:
            return (
                c.execute("UPDATE credentials SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (time.time(), cred_id)).rowcount
                > 0
            )

    def revoke_worker_credentials(self, worker_id: str, *, except_id: str | None = None) -> int:
        with self._lock, self._conn() as c:
            return c.execute(
                "UPDATE credentials SET revoked_at=? WHERE worker_id=? AND kind='worker' AND revoked_at IS NULL AND id != ?",
                (time.time(), worker_id, except_id or ""),
            ).rowcount

    # ── join tokens ────────────────────────────────────────────────────────

    def _join_from_row(self, r: sqlite3.Row) -> JoinToken:
        ap = r["allowed_plugins"]
        return JoinToken(
            id=r["id"],
            pool=r["pool"],
            labels=json.loads(r["labels"] or "[]"),
            allowed_plugins=json.loads(ap) if ap else None,
            max_uses=int(r["max_uses"]),
            uses=int(r["uses"]),
            created_at=r["created_at"],
            expires_at=r["expires_at"],
            revoked_at=r["revoked_at"],
            created_by=r["created_by"],
            note=r["note"] or "",
            workers=json.loads(r["workers"] or "[]"),
            org_id=(r["org_id"] if "org_id" in r.keys() else None),
        )

    def create_join_token(
        self,
        *,
        pool: str | None = None,
        labels: Iterable[str] = (),
        allowed_plugins: Iterable[str] | None = None,
        ttl_s: float = 3600.0,
        max_uses: int = 1,
        created_by: str | None = None,
        note: str = "",
        org_id: str | None = None,
    ) -> tuple[str, JoinToken]:
        if not 60 <= float(ttl_s) <= 7 * 86400:
            raise UserStoreError("ttl_s must be between 60 s and 7 days")
        if not 1 <= int(max_uses) <= 100:
            raise UserStoreError("max_uses must be between 1 and 100")
        pool_clean = _clean_labels([pool] if pool else [], "pool")
        lab = _clean_labels(labels, "label")
        plugins = _clean_labels(allowed_plugins, "plugin") if allowed_plugins is not None else None
        tid, secret, token = _new_token("join")
        now = time.time()
        with self._lock, self._conn() as c:
            # org_id column added by OrgStore migration; tolerate older DBs.
            cols = {r[1] for r in c.execute("PRAGMA table_info(join_tokens)")}
            if "org_id" in cols:
                c.execute(
                    "INSERT INTO join_tokens (id, secret_hash, pool, labels, allowed_plugins, max_uses, created_at, expires_at, created_by, note, org_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        tid,
                        _secret_hash(secret),
                        pool_clean[0] if pool_clean else None,
                        json.dumps(lab),
                        json.dumps(plugins) if plugins is not None else None,
                        int(max_uses),
                        now,
                        now + float(ttl_s),
                        created_by,
                        str(note or "").strip()[:256],
                        (org_id or "").strip() or None,
                    ),
                )
            else:
                c.execute(
                    "INSERT INTO join_tokens (id, secret_hash, pool, labels, allowed_plugins, max_uses, created_at, expires_at, created_by, note)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        tid,
                        _secret_hash(secret),
                        pool_clean[0] if pool_clean else None,
                        json.dumps(lab),
                        json.dumps(plugins) if plugins is not None else None,
                        int(max_uses),
                        now,
                        now + float(ttl_s),
                        created_by,
                        str(note or "").strip()[:256],
                    ),
                )
            row = c.execute("SELECT * FROM join_tokens WHERE id=?", (tid,)).fetchone()
        return token, self._join_from_row(row)

    def consume_join_token(self, token: str, worker_id: str) -> JoinToken:
        """Validate and use one slot of a join token for ``worker_id`` (atomic)."""
        parsed = parse_token(token)
        if parsed is None or parsed[0] != "join":
            raise UserStoreError("Invalid join token", 401, "unauthorized")
        _, tid, secret = parsed
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                row = c.execute("SELECT * FROM join_tokens WHERE id=?", (tid,)).fetchone()
                if row is None or not hmac.compare_digest(row["secret_hash"], _secret_hash(secret)):
                    raise UserStoreError("Invalid join token", 401, "unauthorized")
                jt = self._join_from_row(row)
                if not jt.active:
                    raise UserStoreError("Join token is expired, revoked or used up", 401, "unauthorized")
                workers = [*jt.workers, worker_id]
                c.execute("UPDATE join_tokens SET uses=uses+1, workers=? WHERE id=?", (json.dumps(workers), tid))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            row = c.execute("SELECT * FROM join_tokens WHERE id=?", (tid,)).fetchone()
        return self._join_from_row(row)

    def list_join_tokens(self, *, include_inactive: bool = False) -> list[JoinToken]:
        with self._conn() as c:
            rows = [self._join_from_row(r) for r in c.execute("SELECT * FROM join_tokens ORDER BY created_at DESC")]
        return rows if include_inactive else [j for j in rows if j.active]

    def get_join_token(self, tid: str) -> JoinToken | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM join_tokens WHERE id=?", (tid,)).fetchone()
            return self._join_from_row(row) if row else None

    def revoke_join_token(self, tid: str) -> bool:
        with self._lock, self._conn() as c:
            return c.execute("UPDATE join_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (time.time(), tid)).rowcount > 0


    # ── enrolled workers (join provenance + revocation) ────────────────────

    def enroll_worker(
        self,
        worker_id: str,
        jt: JoinToken,
        *,
        hostname: str = "",
        cert_fingerprint: str | None = None,
        cert_expires_at: float | None = None,
    ) -> dict[str, Any]:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO enrolled_workers (worker_id, join_token_id, pool, labels, allowed_plugins, hostname,"
                " cert_fingerprint, cert_expires_at, enrolled_at, enrolled_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    worker_id,
                    jt.id,
                    jt.pool,
                    json.dumps(jt.labels),
                    json.dumps(jt.allowed_plugins) if jt.allowed_plugins is not None else None,
                    str(hostname or "")[:128],
                    cert_fingerprint,
                    cert_expires_at,
                    time.time(),
                    jt.created_by,
                ),
            )
        return self.get_enrollment(worker_id) or {}

    def update_enrollment_cert(self, worker_id: str, fingerprint: str | None, expires_at: float | None) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE enrolled_workers SET cert_fingerprint=?, cert_expires_at=? WHERE worker_id=?",
                (fingerprint, expires_at, worker_id),
            )

    @staticmethod
    def _enrollment_from_row(r: sqlite3.Row) -> dict[str, Any]:
        ap = r["allowed_plugins"]
        return {
            "worker_id": r["worker_id"],
            "join_token_id": r["join_token_id"],
            "pool": r["pool"],
            "labels": json.loads(r["labels"] or "[]"),
            "allowed_plugins": json.loads(ap) if ap else None,
            "hostname": r["hostname"] or "",
            "cert_fingerprint": r["cert_fingerprint"],
            "cert_expires_at": _iso(r["cert_expires_at"]),
            "enrolled_at": _iso(r["enrolled_at"]),
            "enrolled_by": r["enrolled_by"],
            "revoked_at": _iso(r["revoked_at"]),
            "revoked_by": r["revoked_by"],
            "active": r["revoked_at"] is None,
        }

    def get_enrollment(self, worker_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM enrolled_workers WHERE worker_id=?", (worker_id,)).fetchone()
            return self._enrollment_from_row(row) if row else None

    def list_enrollments(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            return [self._enrollment_from_row(r) for r in c.execute("SELECT * FROM enrolled_workers ORDER BY enrolled_at DESC")]

    def worker_revoked(self, worker_id: str | None) -> bool:
        """True when ``worker_id`` was enrolled via join and later revoked."""
        if not worker_id:
            return False
        with self._conn() as c:
            row = c.execute("SELECT revoked_at FROM enrolled_workers WHERE worker_id=?", (worker_id,)).fetchone()
        return bool(row and row["revoked_at"] is not None)

    def revoke_enrollment(self, worker_id: str, *, revoked_by: str | None = None) -> int:
        """Revoke an enrolled worker: its credentials stop working and its cert is refused."""
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE enrolled_workers SET revoked_at=?, revoked_by=? WHERE worker_id=? AND revoked_at IS NULL",
                (time.time(), revoked_by, worker_id),
            )
        return self.revoke_worker_credentials(worker_id)

    def update_credential_meta(self, credential_id: str, meta: dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT meta FROM credentials WHERE id=?", (credential_id,)).fetchone()
            if row is None:
                raise UserStoreError("Credential not found", 404, "not_found")
            c.execute(
                "UPDATE credentials SET meta=? WHERE id=?",
                (json.dumps(meta, separators=(",", ":")), credential_id),
            )


_STORE: UserStore | None = None
_STORE_PATH: Path | None = None
_STORE_LOCK = threading.Lock()


def get_user_store() -> UserStore:
    """Process-wide store; re-opened when GRAPHYN_USERS_DB / GRAPHYN_HOME moves (tests)."""
    global _STORE, _STORE_PATH
    path = default_store_path()
    with _STORE_LOCK:
        if _STORE is None or _STORE_PATH != path:
            _STORE = UserStore(path)
            _STORE_PATH = path
        return _STORE


def reset_user_store() -> None:
    global _STORE, _STORE_PATH
    with _STORE_LOCK:
        _STORE = None
        _STORE_PATH = None
    try:
        from app.core.trust.orgs import reset_org_store

        reset_org_store()
    except Exception:
        pass
    try:
        from app.core.trust.metering import reset_meter_store

        reset_meter_store()
    except Exception:
        pass


def users_configured() -> bool:
    """True once at least one user exists (cheap: store opened lazily)."""
    try:
        return get_user_store().has_users()
    except Exception:
        return False


__all__ = [
    "Credential",
    "CREDENTIAL_KINDS",
    "JoinToken",
    "MIN_PASSWORD_LEN",
    "PROJECT_ROLES",
    "ROLE_NAMES",
    "SESSION_TTL_S",
    "User",
    "UserStore",
    "UserStoreError",
    "WORKER_CREDENTIAL_TTL_S",
    "default_store_path",
    "get_user_store",
    "hash_password",
    "looks_like_issued_token",
    "parse_token",
    "reset_user_store",
    "users_configured",
    "verify_password",
]
