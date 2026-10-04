# app/core/runs/run_resolve.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Resolve user-supplied run ids (full ids or unique prefixes
                  of >= 8 characters) to the full run directory name.
Owns:             resolve_run_id(), RunIdNotFound, RunIdAmbiguous, MIN_PREFIX.
Public Surface:   resolve_run_id(runs_root, raw) -> str
Must NOT:         Import app.api / app.domain; write anything.
Dependencies:     stdlib (os, re, pathlib).
Reason To Change: Run id format or prefix policy changes.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

MIN_PREFIX = 8
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")


class RunIdNotFound(LookupError):
    """No run matches the id / prefix."""


class RunIdAmbiguous(LookupError):
    """A prefix matches more than one run."""

    def __init__(self, prefix: str, matches: list[str]) -> None:
        self.prefix = prefix
        self.matches = matches
        shown = ", ".join(matches[:5]) + (" …" if len(matches) > 5 else "")
        super().__init__(
            f"Ambiguous run id prefix '{prefix}' matches {len(matches)} runs: {shown}"
        )


def resolve_run_id(runs_root: str | Path, raw: str) -> str:
    """Return the full run id for ``raw`` (exact match, else unique prefix ≥ 8).

    Raises ``ValueError`` (invalid id), ``RunIdNotFound`` or ``RunIdAmbiguous``.
    """
    rid = str(raw or "").strip()
    if not _RUN_ID_RE.match(rid):
        raise ValueError("Invalid run_id")
    root = Path(runs_root)
    if (root / rid).is_dir():
        return rid
    if len(rid) < MIN_PREFIX:
        raise RunIdNotFound(rid)
    try:
        names = [e.name for e in os.scandir(root) if e.name.startswith(rid) and e.is_dir()]
    except OSError:
        names = []
    if not names:
        raise RunIdNotFound(rid)
    if len(names) > 1:
        raise RunIdAmbiguous(rid, sorted(names))
    return names[0]
