# app/core/smtp_notify.py
"""Outbound SMTP helper for run notifications and the send_email plugin.

Credentials via env only (never IR):
  GRAPHYN_SMTP_HOST, GRAPHYN_SMTP_PORT (default 587),
  GRAPHYN_SMTP_USER, GRAPHYN_SMTP_PASSWORD,
  GRAPHYN_SMTP_FROM, GRAPHYN_SMTP_TLS (default 1),
  GRAPHYN_SMTP_DRY_RUN (1 = log + return receipt, no network).

Does not implement IMAP/inbox. Fail-closed when host/from missing unless dry-run.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any

logger = logging.getLogger(__name__)


def smtp_config_from_env() -> dict[str, Any]:
    host = (os.environ.get("GRAPHYN_SMTP_HOST") or "").strip()
    port_raw = (os.environ.get("GRAPHYN_SMTP_PORT") or "587").strip()
    try:
        port = int(port_raw)
    except ValueError:
        port = 587
    user = (os.environ.get("GRAPHYN_SMTP_USER") or "").strip()
    password = (os.environ.get("GRAPHYN_SMTP_PASSWORD") or "").strip()
    # Allow password via secret store name in GRAPHYN_SMTP_PASSWORD_SECRET
    secret_name = (os.environ.get("GRAPHYN_SMTP_PASSWORD_SECRET") or "").strip()
    if secret_name and not password:
        try:
            from app.core.secrets import resolve_secret
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


def send_email(
    *,
    to: str | list[str],
    subject: str,
    body: str,
    from_addr: str | None = None,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """Send a plain-text email via SMTP env config. Returns a receipt dict."""
    cfg = smtp_config_from_env()
    if dry_run is None:
        dry_run = bool(cfg["dry_run"])
    recipients = [to] if isinstance(to, str) else list(to or [])
    recipients = [r.strip() for r in recipients if r and str(r).strip()]
    sender = (from_addr or cfg["from_addr"] or "").strip()
    subject = (subject or "").strip() or "(no subject)"
    body = body if body is not None else ""

    if not recipients:
        raise RuntimeError("send_email: recipient 'to' is required.")
    if dry_run:
        logger.info(
            "smtp dry-run: to=%s subject=%r from=%r host=%r",
            recipients, subject, sender or cfg["from_addr"], cfg["host"] or "(unset)",
        )
        return {
            "ok": True,
            "dry_run": True,
            "to": recipients,
            "from_addr": sender or cfg["from_addr"] or "dry-run@localhost",
            "subject": subject,
            "message": "dry-run: email not sent",
        }

    if not cfg["host"]:
        raise RuntimeError(
            "send_email: needs-credentials — set GRAPHYN_SMTP_HOST "
            "(and GRAPHYN_SMTP_FROM). Or set GRAPHYN_SMTP_DRY_RUN=1."
        )
    if not sender:
        raise RuntimeError(
            "send_email: needs-credentials — set GRAPHYN_SMTP_FROM or pass from_addr."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(str(body))

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as smtp:
            if cfg["tls"]:
                smtp.starttls()
            if cfg["user"]:
                smtp.login(cfg["user"], cfg["password"] or "")
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
    }
