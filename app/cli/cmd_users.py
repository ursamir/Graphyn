# app/cli/cmd_users.py
"""
Bounded Context:  CLI Interface
Responsibility:   users create-admin / add / list / set-roles / disable /
                  enable / reset-password / token / member subcommands —
                  local administration of the control plane's user store
                  (run on the control host, e.g. ``docker exec graphyn-api``).
Owns:             cmd_users_* functions, add_users_parser().
Public Surface:   add_users_parser(subparsers).
Must NOT:         Take passwords from argv (prompt or GRAPHYN_NEW_PASSWORD only);
                  print token secrets except the one being created.
                  Must not import app.api.
Dependencies:     app.core.trust.users, app.core.trust.audit, stdlib (getpass, json).
Reason To Change: User admin CLI flags or output change.
"""
from __future__ import annotations

import getpass
import json
import os
import sys


def _store():
    from app.core.trust.users import get_user_store

    return get_user_store()


def _password(confirm: bool = True) -> str:
    env = os.environ.get("GRAPHYN_NEW_PASSWORD")
    if env:
        return env
    if not sys.stdin.isatty():
        line = sys.stdin.readline().rstrip("\n")
        if line:
            return line
        raise SystemExit("No password: set GRAPHYN_NEW_PASSWORD or pipe it on stdin")
    pw = getpass.getpass("Password (min 10 chars): ")
    if confirm and getpass.getpass("Repeat password: ") != pw:
        raise SystemExit("Passwords do not match")
    return pw


def _audit(action: str, resource_type: str, resource_id: str, meta: dict) -> None:
    try:
        from app.core.trust.audit import record_audit

        record_audit(actor=f"cli:{getpass.getuser()}", action=action, resource_type=resource_type, resource_id=resource_id, meta=meta)
    except Exception:
        pass


def _user(ref: str):
    store = _store()
    u = store.get_user(ref) or store.get_user_by_username(ref)
    if u is None:
        raise SystemExit(f"No such user: {ref}")
    return u


def _fail(exc: Exception) -> None:
    raise SystemExit(str(exc))


def cmd_users_create_admin(args):
    from app.core.trust.users import UserStoreError

    try:
        u = _store().create_user(args.username, _password(), roles=["admin"], display_name=args.display_name or "", created_by=f"cli:{getpass.getuser()}")
    except UserStoreError as exc:
        _fail(exc)
    _audit("user.create", "user", u.id, {"username": u.username, "roles": u.roles, "via": "cli"})
    print(f"Created admin {u.username} ({u.id}). Sign in at the console with this username.")


def cmd_users_add(args):
    from app.core.trust.users import UserStoreError

    roles = [r for r in (args.roles or "viewer").split(",") if r.strip()]
    appr = [r for r in (args.approver_roles or "").split(",") if r.strip()]
    try:
        u = _store().create_user(args.username, _password(), roles=roles, approver_roles=appr, display_name=args.display_name or "", created_by=f"cli:{getpass.getuser()}")
    except UserStoreError as exc:
        _fail(exc)
    _audit("user.create", "user", u.id, {"username": u.username, "roles": u.roles, "via": "cli"})
    print(f"Created {u.username} ({u.id}) roles={','.join(u.roles)}")


def cmd_users_list(args):
    users = [u.public() for u in _store().list_users()]
    if getattr(args, "json", False):
        print(json.dumps(users, indent=2))
        return
    if not users:
        print("No users. Create the first admin: graphyn users create-admin <username>")
        return
    for u in users:
        flag = " (disabled)" if u["disabled"] else ""
        mem = ", ".join(f"{p}:{r}" for p, r in u["memberships"].items())
        print(f"{u['username']:<20} {','.join(u['roles']):<24} {u['id']}{flag}" + (f"  projects: {mem}" if mem else ""))


def cmd_users_set_roles(args):
    from app.core.trust.users import UserStoreError

    u = _user(args.user)
    kw = {"roles": [r for r in args.roles.split(",") if r.strip()]}
    if args.approver_roles is not None:
        kw["approver_roles"] = [r for r in args.approver_roles.split(",") if r.strip()]
    try:
        after = _store().update_user(u.id, **kw)
    except UserStoreError as exc:
        _fail(exc)
    _audit("user.update", "user", u.id, {"username": u.username, "roles_before": u.roles, "roles_after": after.roles, "via": "cli"})
    print(f"{after.username}: roles={','.join(after.roles)} approver_roles={','.join(after.approver_roles) or '-'}")


def _set_disabled(args, disabled: bool) -> None:
    from app.core.trust.users import UserStoreError

    u = _user(args.user)
    try:
        _store().update_user(u.id, disabled=disabled)
    except UserStoreError as exc:
        _fail(exc)
    _audit("user.update", "user", u.id, {"username": u.username, "changes": {"disabled": disabled}, "via": "cli"})
    print(f"{u.username}: {'disabled (sessions and tokens revoked)' if disabled else 'enabled'}")


def cmd_users_disable(args):
    _set_disabled(args, True)


def cmd_users_enable(args):
    _set_disabled(args, False)


def cmd_users_reset_password(args):
    from app.core.trust.users import UserStoreError

    u = _user(args.user)
    try:
        _store().update_user(u.id, password=_password())
    except UserStoreError as exc:
        _fail(exc)
    _audit("user.update", "user", u.id, {"username": u.username, "changes": {"password_reset": True}, "via": "cli"})
    print(f"{u.username}: password reset; existing sessions signed out")


def cmd_users_token(args):
    u = _user(args.user)
    token, cred = _store().issue_credential(
        "api", user_id=u.id, name=args.name, ttl_s=max(1, int(args.days)) * 86400, created_by=f"cli:{getpass.getuser()}"
    )
    _audit("token.create", "credential", cred.id, {"user_id": u.id, "name": cred.name, "via": "cli"})
    print(token)
    print(f"# token id {cred.id} for {u.username}, expires {cred.public()['expires_at']} — shown once", file=sys.stderr)


def cmd_users_member(args):
    from app.core.trust.users import UserStoreError

    u = _user(args.user)
    store = _store()
    if args.role == "remove":
        store.remove_membership(args.project, u.id)
        _audit("project.member_remove", "project", args.project, {"user_id": u.id, "via": "cli"})
        print(f"{u.username} removed from {args.project}")
        return
    try:
        store.set_membership(args.project, u.id, args.role, added_by=f"cli:{getpass.getuser()}")
    except UserStoreError as exc:
        _fail(exc)
    _audit("project.member_set", "project", args.project, {"user_id": u.id, "role": args.role, "via": "cli"})
    print(f"{u.username} is {args.role} of {args.project}")


def add_users_parser(subparsers) -> None:
    from app.core.trust.users import PROJECT_ROLES, ROLE_NAMES

    p = subparsers.add_parser(
        "users",
        help="Manage console users, roles and project membership (control host)",
        description=(
            "Local administration of the control plane's user store "
            "(GRAPHYN_HOME/auth/users.db). Passwords come from a prompt, stdin or "
            "GRAPHYN_NEW_PASSWORD — never argv. Roles: " + ", ".join(ROLE_NAMES) + "."
        ),
    )
    sub = p.add_subparsers(dest="users_command", metavar="ACTION")
    sub.required = True
    s = sub.add_parser("create-admin", help="Create an admin user (first sign-in)")
    s.add_argument("username")
    s.add_argument("--display-name")
    s.set_defaults(func=cmd_users_create_admin)
    s = sub.add_parser("add", help="Create a user")
    s.add_argument("username")
    s.add_argument("--roles", default="viewer", help="Comma-separated: " + ",".join(ROLE_NAMES))
    s.add_argument("--approver-roles", default="", help="Comma-separated gate approver roles (e.g. qa-lead,ml-lead)")
    s.add_argument("--display-name")
    s.set_defaults(func=cmd_users_add)
    s = sub.add_parser("list", help="List users")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_users_list)
    s = sub.add_parser("set-roles", help="Replace a user's roles")
    s.add_argument("user", help="Username or id")
    s.add_argument("roles", help="Comma-separated roles")
    s.add_argument("--approver-roles", default=None)
    s.set_defaults(func=cmd_users_set_roles)
    for name, fn, hlp in (
        ("disable", cmd_users_disable, "Disable a user (revokes sessions + tokens)"),
        ("enable", cmd_users_enable, "Re-enable a user"),
        ("reset-password", cmd_users_reset_password, "Set a new password"),
    ):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("user")
        s.set_defaults(func=fn)
    s = sub.add_parser("token", help="Issue a personal API token for a user (printed once)")
    s.add_argument("user")
    s.add_argument("--name", default="cli")
    s.add_argument("--days", type=int, default=90)
    s.set_defaults(func=cmd_users_token)
    s = sub.add_parser("member", help="Set a user's role in a project (or 'remove')")
    s.add_argument("project")
    s.add_argument("user")
    s.add_argument("role", choices=[*PROJECT_ROLES, "remove"])
    s.set_defaults(func=cmd_users_member)
