# app/core/trust/rbac.py
"""
Bounded Context:  BC6 — Observability & Storage (access control)
Responsibility:   Role → permission model and the single route policy table
                  the API middleware enforces for user identities: which
                  permission each ``METHOD /api/v1/...`` needs and which
                  project (if any) the request touches, so membership can be
                  checked in one place instead of in every router.
Owns:             PERMISSIONS, ROLE_PERMISSIONS, PROJECT_ROLE_PERMISSIONS,
                  permissions_for(), required_permission(), project_of_request(),
                  authorize(), check_project_permission(), can_see_all_projects(),
                  visible_projects_filter().
Public Surface:   The functions above.
Must NOT:         Import app.api / app.domain / execution; read request bodies.
Dependencies:     stdlib (re), app.core.config (runs_dir) lazily.
Reason To Change: A route is added / its sensitivity changes, or roles change.

Policy:
  * Global roles grant permissions everywhere they apply.
  * Project-scoped requests (``/projects/{name}/…``, ``/hooks/{ws}/…``,
    ``/data/outputs/{project}/…``, ``?project=`` / ``?workspace=``, and
    ``/runs/{id}/…`` via the run's ``meta.json`` project) additionally need a
    membership in that project unless the role can see all projects
    (admin / auditor / operator). A project membership role grants its own
    permissions inside that project (e.g. ``builder`` there may edit and run).
  * Body-scoped routes (run / schedule create) pass the middleware with a
    permission held in any membership; the router checks the body's project.
  * Unknown routes fail closed: GET needs ``read``; anything else ``admin``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote

PERMISSIONS: tuple[str, ...] = (
    "read",
    "pipelines.write",
    "runs.execute",
    "approve",
    "audit.read",
    "workers.admin",
    "plugins.admin",
    "credentials.admin",
    "system.admin",
    "users.admin",
    "projects.all",
    "admin",
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset(PERMISSIONS),
    "operator": frozenset(
        {"read", "runs.execute", "workers.admin", "plugins.admin", "credentials.admin", "system.admin", "projects.all"}
    ),
    "builder": frozenset({"read", "pipelines.write", "runs.execute"}),
    "approver": frozenset({"read", "approve"}),
    "auditor": frozenset({"read", "audit.read", "projects.all"}),
    "viewer": frozenset({"read"}),
}

PROJECT_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset({"read", "pipelines.write", "runs.execute", "approve", "project.members"}),
    "builder": frozenset({"read", "pipelines.write", "runs.execute"}),
    "approver": frozenset({"read", "approve"}),
    "viewer": frozenset({"read"}),
}

# (method, path regex, permission). First match wins. Paths are /api/v1-relative.
_R = r"[^/]+"
_POLICY: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    (m, re.compile(rf"^/api/v1{p}/?$"), perm)
    for m, p, perm in (
        # identity / self-service
        ("GET", r"/me", "authenticated"),
        ("*", r"/me/tokens(/.*)?", "authenticated"),
        ("POST", r"/auth/(logout|login)", "authenticated"),
        ("GET", r"/auth/oidc(/.*)?", "authenticated"),
        ("POST", r"/auth/oidc(/.*)?", "authenticated"),
        ("POST", r"/auth/bootstrap", "users.admin"),
        ("POST", r"/billing/webhook", "authenticated"),
        ("GET", r"/billing/status", "system.admin"),
        ("POST", r"/me/password", "authenticated"),
        # user admin
        ("*", r"/users(/.*)?", "users.admin"),
        ("GET", r"/agents(/.*)?", "users.admin"),
        ("*", r"/agents(/.*)?", "users.admin"),
        ("GET", r"/compliance(/.*)?", "audit.read"),
        ("*", r"/compliance(/.*)?", "users.admin"),
        ("GET", r"/orgs", "authenticated"),
        ("POST", r"/orgs", "authenticated"),
        ("GET", rf"/orgs/{_R}", "authenticated"),
        ("PATCH", rf"/orgs/{_R}", "authenticated"),
        ("POST", rf"/orgs/{_R}/activate", "authenticated"),
        ("GET", rf"/orgs/{_R}/members", "authenticated"),
        ("*", rf"/orgs/{_R}/members(/.*)?", "authenticated"),
        ("GET", rf"/orgs/{_R}/(usage|quotas|meter-events)", "authenticated"),
        ("PUT", rf"/orgs/{_R}/quotas", "authenticated"),
        ("GET", rf"/projects/{_R}/members", "read"),
        ("*", rf"/projects/{_R}/members(/.*)?", "project.members"),
        # audit
        ("GET", r"/audit(/.*)?", "audit.read"),
        # workers / join tokens (worker protocol routes are handled by worker scope)
        ("*", r"/workers/join-tokens(/.*)?", "workers.admin"),
        ("*", r"/workers/credentials(/.*)?", "workers.admin"),
        ("GET", r"/workers/enrollments", "workers.admin"),
        ("GET", rf"/workers/{_R}/credentials", "workers.admin"),
        ("POST", rf"/workers/{_R}/credentials/rotate", "workers.admin"),
        ("POST", r"/workers/join", "authenticated"),
        ("PATCH", rf"/workers/{_R}", "workers.admin"),
        ("DELETE", rf"/workers/{_R}", "workers.admin"),
        ("POST", rf"/workers/{_R}/(drain|revoke)", "workers.admin"),
        ("POST", r"/workers/register", "workers.admin"),
        ("POST", rf"/workers/{_R}/heartbeat", "workers.admin"),
        ("POST", r"/jobs/claim", "workers.admin"),
        ("POST", rf"/jobs/{_R}/(complete|events)", "workers.admin"),
        ("POST", rf"/jobs/{_R}/cancel", "runs.execute"),
        ("POST", r"/artifacts/blob", "workers.admin"),
        ("POST", r"/artifacts/blob/sign", "workers.admin"),
        # plugins
        ("GET", r"/plugins(/.*)?", "read"),
        ("*", r"/plugins(/.*)?", "plugins.admin"),
        # credentials (list/get return redacted fields only)
        ("GET", r"/credentials(/.*)?", "read"),
        ("*", r"/credentials(/.*)?", "credentials.admin"),
        # system
        ("GET", r"/system/metrics", "system.admin"),
        ("GET", r"/system/webhooks", "system.admin"),
        ("PUT", r"/system/webhooks", "system.admin"),
        ("POST", r"/system/webhooks/test", "system.admin"),
        ("POST", r"/system/cleanup", "system.admin"),
        ("POST", r"/system/notifications/mark-read", "read"),
        ("POST", rf"/system/schedules/{_R}/run", "runs.execute"),
        ("POST", r"/system/schedules/tick", "system.admin"),
        ("*", r"/system/schedules(/.*)?", "pipelines.write"),
        # approvals
        ("POST", rf"/runs/{_R}/gates/{_R}/decision", "approve"),
        ("POST", rf"/proposals/{_R}/(accept|reject)", "approve"),
        ("POST", rf"/models/{_R}/approve-prod", "approve"),
        # governance: waiving separation of duties is a users/approvals admin power
        ("PUT", r"/models/promotion-policy", "users.admin"),
        ("POST", rf"/projects/{_R}/pipelines/{_R}/promote", "approve"),
        ("POST", rf"/projects/{_R}/ship/packages/{_R}/promote", "approve"),
        ("POST", rf"/runs/{_R}/promote", "approve"),
        # execution
        ("POST", r"/pipelines/run(-async)?", "runs.execute"),
        ("POST", rf"/runs/{_R}/(cancel|pause|resume|replay|restore|verify)", "runs.execute"),
        ("POST", rf"/artifacts/{_R}/replay", "runs.execute"),
        ("POST", rf"/projects/{_R}/quality-check", "runs.execute"),
        ("POST", rf"/hooks/{_R}/{_R}", "runs.execute"),
        ("POST", r"/pipelines/validate", "read"),
        ("POST", rf"/nodes/{_R}/validate-config", "read"),
        ("POST", r"/pipelines/templates/sync-examples", "system.admin"),
        # reads
        ("GET", r"/.*", "read"),
        # every other mutation edits pipelines / projects / data / models
        ("*", r"/(projects|pipelines|data|ingest|models|proposals|runs|ship|experiments)(/.*)?", "pipelines.write"),
    )
)

# Routes whose project is in the JSON body: the middleware accepts a permission
# held via *any* membership and the router re-checks the exact project with
# check_project_permission().
_BODY_SCOPED: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/api/v1/pipelines/run(-async)?/?$"),
    re.compile(r"^/api/v1/system/schedules/?$"),
)

_PROJECT_PATHS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/api/v1/projects/(?P<p>[^/]+)(/|$)"),
    re.compile(r"^/api/v1/hooks/(?P<p>[^/]+)/"),
    re.compile(r"^/api/v1/data/outputs/(?P<p>[^/]+)/"),
)
_RUN_PATH = re.compile(r"^/api/v1/runs/(?P<r>[A-Za-z0-9_.-]+)(/|$)")
_RUN_LIST_SEGMENTS = frozenset({"compare", "live", "active", "search", "summary", "stats"})
_PROJECT_QUERY_KEYS = ("project", "workspace")


def permissions_for(roles: Iterable[str]) -> frozenset[str]:
    out: set[str] = set()
    for r in roles or []:
        out |= ROLE_PERMISSIONS.get(str(r), frozenset())
    return frozenset(out)


def can_see_all_projects(roles: Iterable[str]) -> bool:
    return "projects.all" in permissions_for(roles)


def required_permission(method: str, path: str) -> str:
    m = str(method or "").upper()
    if m == "HEAD":
        m = "GET"
    for pm, rx, perm in _POLICY:
        if (pm == "*" or pm == m) and rx.match(path or ""):
            return perm
    return "read" if m == "GET" else "admin"


def _run_project(run_id: str) -> str | None:
    try:
        from app.core.config import runs_dir

        meta_path = Path(runs_dir()) / run_id / "meta.json"
        if not meta_path.is_file():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(meta, dict):
        return None
    proj = meta.get("project")
    if not proj and isinstance(meta.get("meta"), dict):
        proj = meta["meta"].get("project")
    return str(proj).strip() or None if proj else None


def project_of_request(path: str, query_string: str = "") -> str | None:
    """Project a request is scoped to, or None for global routes."""
    for rx in _PROJECT_PATHS:
        m = rx.match(path or "")
        if m:
            return unquote(m.group("p")) or None
    m = _RUN_PATH.match(path or "")
    if m and m.group("r") not in _RUN_LIST_SEGMENTS:
        proj = _run_project(m.group("r"))
        if proj:
            return proj
    if query_string:
        q = parse_qs(query_string, keep_blank_values=False)
        for key in _PROJECT_QUERY_KEYS:
            vals = q.get(key)
            if vals and vals[0].strip():
                return vals[0].strip()
    return None


def effective_permissions(ident: dict[str, Any], project: str | None) -> frozenset[str]:
    perms = set(permissions_for(ident.get("roles") or []))
    if project:
        prole = (ident.get("memberships") or {}).get(project)
        if prole:
            perms |= PROJECT_ROLE_PERMISSIONS.get(str(prole), frozenset())
    return frozenset(perms)


def authorize(ident: dict[str, Any] | None, method: str, path: str, query_string: str = "") -> tuple[int, str] | None:
    """None when allowed, else ``(status, message)`` for a user identity.

    Non-user/agent identities (legacy shared token, unauthenticated dev, workers)
    are not subject to this table — the caller decides. Agents use the same
    permission table as users.
    """
    if not ident or ident.get("kind") not in ("user", "agent"):
        return None
    need = required_permission(method, path)
    if need == "authenticated":
        return None
    project = project_of_request(path, query_string)
    roles = ident.get("roles") or []
    perms = effective_permissions(ident, project)
    if project is None and any(rx.match(path or "") for rx in _BODY_SCOPED):
        for prole in (ident.get("memberships") or {}).values():
            perms = perms | PROJECT_ROLE_PERMISSIONS.get(str(prole), frozenset())
    # Org boundary: project must belong to the caller's active org (when set).
    if project and ident.get("org_id"):
        try:
            from app.core.trust.orgs import get_org_store

            porg = get_org_store().project_org_id(project)
            if porg and porg != ident.get("org_id"):
                return 403, f"Project '{project}' is outside your active organization"
        except Exception:
            pass
    if project and not can_see_all_projects(roles) and project not in (ident.get("memberships") or {}):
        from app.core.trust.orgs import org_can_see_all_projects

        if not org_can_see_all_projects(ident.get("org_role")):
            return 403, f"You are not a member of project '{project}'"
    if need in perms or "admin" in perms:
        return None
    # Global user admins may manage project membership without being project owner.
    if need == "project.members" and ("users.admin" in perms or "users.admin" in permissions_for(roles)):
        return None
    return 403, f"Permission '{need}' required for {method.upper()} {path}"


def check_project_permission(ident: dict[str, Any] | None, project: str | None, perm: str) -> str | None:
    """Error message when a user may not ``perm`` inside ``project`` (body-scoped requests)."""
    if not ident or ident.get("kind") not in ("user", "agent"):
        return None
    roles = ident.get("roles") or []
    if project and not can_see_all_projects(roles) and project not in (ident.get("memberships") or {}):
        return f"You are not a member of project '{project}'"
    perms = effective_permissions(ident, project or None)
    if perm in perms or "admin" in perms:
        return None
    return f"Permission '{perm}' required" + (f" in project '{project}'" if project else "")


def visible_projects_filter(ident: dict[str, Any] | None):
    """Predicate ``project_name -> bool`` for listings (None = see everything).

    User identities are scoped to the active org's projects. Within the org,
    global ``projects.all`` or org owner/admin see every org project; others
    still need project membership. Non-user identities (legacy bearer) are
    unscoped (break-glass).
    """
    if not ident or ident.get("kind") not in ("user", "agent"):
        return None
    org_id = ident.get("org_id")
    org_projects: set[str] | None = None
    if org_id:
        try:
            from app.core.trust.orgs import get_org_store

            org_projects = get_org_store().projects_in_org(str(org_id))
        except Exception:
            org_projects = set()
    else:
        # User with no org membership sees nothing (tenancy fail-closed).
        return lambda name: False

    from app.core.trust.orgs import org_can_see_all_projects

    if can_see_all_projects(ident.get("roles") or []) or org_can_see_all_projects(ident.get("org_role")):
        return lambda name, _op=org_projects: str(name or "") in _op

    allowed = set((ident.get("memberships") or {}).keys()) & org_projects
    return lambda name, _a=allowed: str(name or "") in _a


__all__ = [
    "PERMISSIONS",
    "PROJECT_ROLE_PERMISSIONS",
    "ROLE_PERMISSIONS",
    "authorize",
    "can_see_all_projects",
    "check_project_permission",
    "effective_permissions",
    "permissions_for",
    "project_of_request",
    "required_permission",
    "visible_projects_filter",
]
