# app/core/notify/smtp_notify.py
"""Outbound SMTP helper for run notifications and the send_email plugin.

Credential precedence:
  1. Explicit connection_id / credentials dict (kind=smtp)
  2. Workspace default smtp connection
  3. Env bootstrap (GRAPHYN_SMTP_*)

Never embed raw secrets in IR. Fail-closed when host/from missing unless dry-run.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any

logger = logging.getLogger(__name__)


def smtp_dry_run_forced() -> bool:
    """True when the operator forces SMTP dry-run server-wide (GRAPHYN_SMTP_DRY_RUN)."""
    return (os.environ.get("GRAPHYN_SMTP_DRY_RUN") or "0").strip().lower() in {"1", "true", "yes", "on"}


class _PinnedSMTP(smtplib.SMTP):
    """smtplib.SMTP that dials a pre-validated IP; STARTTLS still verifies the hostname."""

    def __init__(self, host: str = "", port: int = 0, *, pinned_ip: str | None = None, **kw: Any):
        self._pinned_ip = pinned_ip
        super().__init__(host, port, **kw)

    def _get_socket(self, host, port, timeout):  # type: ignore[override]
        import socket

        target = self._pinned_ip or host
        if timeout is not None and not timeout:
            raise ValueError("Non-blocking socket (timeout=0) is not supported")
        return socket.create_connection((target, port), timeout, self.source_address)


def smtp_config_from_env() -> dict[str, Any]:
    host = (os.environ.get("GRAPHYN_SMTP_HOST") or "").strip()
    port_raw = (os.environ.get("GRAPHYN_SMTP_PORT") or "587").strip()
    try:
        port = int(port_raw)
    except ValueError:
        port = 587
    user = (os.environ.get("GRAPHYN_SMTP_USER") or "").strip()
    password = (os.environ.get("GRAPHYN_SMTP_PASSWORD") or "").strip()
    secret_name = (os.environ.get("GRAPHYN_SMTP_PASSWORD_SECRET") or "").strip()
    if secret_name and not password:
        try:
            from app.core.trust.secrets import resolve_secret
            password = resolve_secret(secret_name) or ""
        except Exception:
            password = os.environ.get(secret_name, "").strip()
    from_addr = (os.environ.get("GRAPHYN_SMTP_FROM") or "").strip()
    tls = (os.environ.get("GRAPHYN_SMTP_TLS") or "1").strip().lower() in {"1", "true", "yes", "on"}
    dry_run = (os.environ.get("GRAPHYN_SMTP_DRY_RUN") or "0").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "from_addr": from_addr,
        "tls": tls,
        "dry_run": dry_run,
    }


def smtp_config_from_credentials(
    *,
    connection_id: str | None = None,
    credentials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve SMTP config via credential store with env fallback."""
    if isinstance(credentials, dict) and (
        credentials.get("host") is not None or credentials.get("payload") is not None
    ):
        payload = credentials.get("payload") if isinstance(credentials.get("payload"), dict) else credentials
        env = smtp_config_from_env()
        port = payload.get("port", env["port"])
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 587
        return {
            "host": str(payload.get("host") or ""),
            "port": port,
            "user": str(payload.get("user") or ""),
            "password": str(payload.get("password") or ""),
            "from_addr": str(payload.get("from_addr") or ""),
            "tls": bool(payload["tls"]) if "tls" in payload else True,
            "dry_run": bool(payload["dry_run"]) if "dry_run" in payload else False,
            "connection_id": credentials.get("connection_id") or connection_id,
            "source": credentials.get("source") or "inline",
        }

    try:
        from app.core.credentials.resolve import resolve_connection
        from app.core.credentials.errors import NeedsCredentialsError

        resolved = resolve_connection(kind="smtp", connection_id=connection_id, required=False)
    except Exception:
        resolved = {"source": "none", "payload": {}, "connection_id": None}

    payload = dict(resolved.get("payload") or {})
    source = resolved.get("source") or "none"
    if source in {"connection", "workspace_default"} and payload:
        port = payload.get("port", 587)
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 587
        return {
            "host": str(payload.get("host") or ""),
            "port": port,
            "user": str(payload.get("user") or ""),
            "password": str(payload.get("password") or ""),
            "from_addr": str(payload.get("from_addr") or ""),
            "tls": bool(payload["tls"]) if "tls" in payload else True,
            "dry_run": bool(payload["dry_run"]) if "dry_run" in payload else False,
            "connection_id": resolved.get("connection_id"),
            "source": source,
        }

    # Env bootstrap
    cfg = smtp_config_from_env()
    cfg["connection_id"] = None
    cfg["source"] = "env" if cfg.get("host") or cfg.get("dry_run") else "none"
    # Merge any partial env payload from resolve
    for k, v in payload.items():
        if v not in (None, "") and not cfg.get(k):
            cfg[k] = v
    return cfg


def send_email(
    *,
    to: str | list[str],
    subject: str,
    body: str,
    from_addr: str | None = None,
    dry_run: bool | None = None,
    connection_id: str | None = None,
    credentials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a plain-text email via SMTP credentials. Returns a receipt dict."""
    cfg = smtp_config_from_credentials(connection_id=connection_id, credentials=credentials)
    if dry_run is None:
        dry_run = bool(cfg.get("dry_run"))
    # F19: GRAPHYN_SMTP_DRY_RUN=1 is a server-wide kill switch — it forces
    # preview mode even when a connection payload says dry_run=false.
    if smtp_dry_run_forced():
        dry_run = True
    recipients = [to] if isinstance(to, str) else list(to or [])
    recipients = [r.strip() for r in recipients if r and str(r).strip()]
    sender = (from_addr or cfg.get("from_addr") or "").strip()
    subject = (subject or "").strip() or "(no subject)"
    body = body if body is not None else ""

    if not recipients:
        raise RuntimeError("send_email: recipient 'to' is required.")
    if dry_run:
        logger.info(
            "smtp dry-run: to=%s subject=%r from=%r host=%r source=%s",
            recipients, subject, sender or cfg.get("from_addr"),
            cfg.get("host") or "(unset)", cfg.get("source"),
        )
        return {
            "ok": True,
            "dry_run": True,
            "to": recipients,
            "from_addr": sender or cfg.get("from_addr") or "dry-run@localhost",
            "subject": subject,
            "message": "dry-run: email not sent",
            "connection_id": cfg.get("connection_id"),
            "source": cfg.get("source"),
        }

    if not cfg.get("host"):
        from app.core.credentials.errors import NeedsCredentialsError
        raise NeedsCredentialsError(
            "send_email: needs-credentials — set smtp connection "
            "(or GRAPHYN_SMTP_HOST / GRAPHYN_SMTP_FROM). Or set dry_run / GRAPHYN_SMTP_DRY_RUN=1."
        )
    if not sender:
        from app.core.credentials.errors import NeedsCredentialsError
        raise NeedsCredentialsError(
            "send_email: needs-credentials — set from_addr on smtp connection "
            "or GRAPHYN_SMTP_FROM / pass from_addr."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(str(body))

    # F19 (F-02): SMTP is network egress too — resolve + validate the relay
    # against the egress policy and connect to the validated IP only.
    from app.core.trust.egress import HttpEgressError, check_egress_host

    try:
        target = check_egress_host(str(cfg["host"]), int(cfg["port"]), purpose="SMTP")
    except HttpEgressError as exc:
        raise RuntimeError(f"send_email: {exc}") from exc
    pinned_ip = target.ips[0] if target.ips else None

    try:
        with _PinnedSMTP(cfg["host"], int(cfg["port"]), timeout=30, pinned_ip=pinned_ip) as smtp:
            if cfg.get("tls"):
                smtp.starttls()
            if cfg.get("user"):
                smtp.login(cfg["user"], cfg.get("password") or "")
            smtp.send_message(msg)
    except Exception as exc:
        logger.warning("smtp send failed: %s", exc)
        raise RuntimeError(f"send_email: SMTP send failed: {exc}") from exc

    return {
        "ok": True,
        "dry_run": False,
        "to": recipients,
        "from_addr": sender,
        "subject": subject,
        "message": "sent",
        "connection_id": cfg.get("connection_id"),
        "source": cfg.get("source"),
    }
