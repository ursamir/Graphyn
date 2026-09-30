# app/cli/cmd_secrets.py
"""
Bounded Context:  CLI Interface
Responsibility:   secrets list/set/delete subcommands.
Owns:             cmd_secrets_list, cmd_secrets_set, cmd_secrets_delete
Public Surface:   cmd_secrets_list, cmd_secrets_set, cmd_secrets_delete
Must NOT:         Contain pipeline execution logic. Must not import app.api.
Dependencies:     app.core.sdk and the core package each command calls.
Reason To Change: That subcommand's flags or output change.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import yaml

def cmd_secrets_list(args):
    """List stored secret names (never values)."""
    from app.core.trust.secrets import list_secret_names

    names = list_secret_names()
    if getattr(args, "json", False):
        print(json.dumps({"names": names}))
        return
    if not names:
        print("No secrets stored.")
        return
    for name in names:
        print(name)


def cmd_secrets_set(args):
    """Store a named secret from process env or stdin — never from argv."""
    from app.core.trust.secrets import SecretError, set_secret

    name = args.name
    value = os.environ.get(name, "")
    if not value:
        if sys.stdin.isatty():
            print(f"Enter value for {name} (stdin, not echoed back):", file=sys.stderr)
        value = sys.stdin.read()
    try:
        stored = set_secret(name, value)
    except SecretError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Stored secret {stored} (value not shown).")


def cmd_secrets_delete(args):
    from app.core.trust.secrets import SecretError, delete_secret

    try:
        found = delete_secret(args.name)
    except SecretError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    if not found:
        print(f"Error: secret {args.name!r} not found.", file=sys.stderr)
        sys.exit(1)
    print(f"Deleted secret {args.name}.")
