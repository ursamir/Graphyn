# app/core/distributed/security.py
"""
Bounded Context:  BC5 — Execution Runtime (Mode B WAVE-1)
Responsibility:   Forbid inline secrets on remote job configs and redact
                  secret-shaped payloads in job events / complete results
                  before they persist on the control plane.
Owns:             assert_remote_config_safe(), redact_job_events(),
                  redact_job_result_payload().
Public Surface:   The functions above.
Must NOT:         Import app.api / app.domain.
Dependencies:     app.core.ir.secret_policy, app.core.trust.egress (lazy).
Reason To Change: Secret key patterns or redaction policy evolve.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from app.core.ir.secret_policy import (
    InlineSecretError,
    find_inline_secrets,
)

_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-+=/]{8,}")
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_SECRET_KEY_RE = re.compile(
    r"(?:^|_)(api_key|apikey|access_token|auth_token|password|passwd|"
    r"secret|hmac_secret|client_secret|private_key|token)$",
    re.IGNORECASE,
)
_ALLOW_KEYS = frozenset(
    {
        "auth_env",
        "api_key_env",
        "token_env",
        "secret_env",
        "hmac_secret_env",
        "password_env",
        "secret_name",
        "secrets_ref",
        "connection_id",
        "credential_id",
    }
)
_VALUE_SECRET_RE = re.compile(
    r"(?:"
    r"sk-(?:ant-)?[A-Za-z0-9_\-]{16,}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r")"
)


def assert_remote_config_safe(config: dict[str, Any] | None) -> dict[str, Any]:
    """Deep-copy ``config`` and refuse inline secrets (refs like *_env OK).

    Reuses :func:`find_inline_secrets` against a one-node fake graph so remote
    enqueue shares the same policy as Graph IR validation.
    """
    cfg = copy.deepcopy(dict(config or {}))
    hits = find_inline_secrets(
        {"nodes": [{"id": "remote", "node_type": "x", "config": cfg}]}
    )
    if hits:
        shown = ", ".join(hits[:8])
        more = f" (+{len(hits) - 8} more)" if len(hits) > 8 else ""
        raise InlineSecretError(
            "Inline secrets are not allowed on remote job configs. "
            f"Use *_env / secret_name / connection_id refs. Found: {shown}{more}"
        )
    return cfg


# Back-compat alias used by callers / docs.
strip_inline_secrets_from_config = assert_remote_config_safe


def _is_secret_key(key: str) -> bool:
    low = (key or "").strip().lower()
    if not low or low in _ALLOW_KEYS or any(low.endswith(s) for s in ("_env", "_secret_name", "_ref")):
        return False
    if low in {
        "api_key",
        "apikey",
        "access_token",
        "auth_token",
        "password",
        "passwd",
        "secret",
        "hmac_secret",
        "client_secret",
        "private_key",
        "token",
    }:
        return True
    return bool(_SECRET_KEY_RE.search(low))


def _redact_string(value: str) -> str:
    from app.core.trust.egress import redact_webhook_url_for_api

    s = value
    if _VALUE_SECRET_RE.search(s):
        return "***"
    if _BEARER_RE.search(s):
        return _BEARER_RE.sub(r"\1***", s)
    if "http://" in s.lower() or "https://" in s.lower():

        def _sub(m: re.Match[str]) -> str:
            return redact_webhook_url_for_api(m.group(0)) or "***"

        return _URL_IN_TEXT_RE.sub(_sub, s)
    return s


def _redact_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            ks = str(k)
            if _is_secret_key(ks) and not isinstance(v, (dict, list)):
                out[ks] = "***" if v not in (None, "") else v
            elif isinstance(v, str):
                out[ks] = _redact_string(v)
            else:
                out[ks] = _redact_obj(v)
        return out
    if isinstance(obj, list):
        return [_redact_obj(x) for x in obj]
    if isinstance(obj, str):
        return _redact_string(obj)
    return obj


def redact_job_events(events: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Redact secret-shaped keys / bearer tokens / webhook URLs in event dicts."""
    out: list[dict[str, Any]] = []
    for e in events or []:
        if isinstance(e, dict):
            out.append(_redact_obj(dict(e)))
        else:
            out.append(e)  # type: ignore[arg-type]
    return out


def redact_job_result_payload(result: Any) -> Any:
    """Redact events/error on a JobResult (or dict) before control persistence."""
    if result is None:
        return result
    if hasattr(result, "model_copy"):
        updates: dict[str, Any] = {}
        ev = getattr(result, "events", None)
        if ev:
            updates["events"] = redact_job_events(list(ev))
        err = getattr(result, "error", None)
        if isinstance(err, str) and err:
            updates["error"] = _redact_string(err)
        return result.model_copy(update=updates) if updates else result
    if isinstance(result, dict):
        out = dict(result)
        if out.get("events"):
            out["events"] = redact_job_events(list(out["events"]))
        if isinstance(out.get("error"), str) and out["error"]:
            out["error"] = _redact_string(out["error"])
        return out
    return result
