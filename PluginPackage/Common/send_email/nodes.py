"""SendEmailNode — outbound SMTP via GRAPHYN_SMTP_* (dry-run capable)."""
from __future__ import annotations

import importlib
import logging
import re
import time
from typing import Any, ClassVar

from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("send_email.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

EmailReceipt = _types.EmailReceipt

log = logging.getLogger(__name__)

# One plain address per entry: no display names, no header-injection characters.
_ADDR_RE = re.compile(r"^[^@\s,;<>\"']+@([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)$")


def _split_addrs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [p.strip() for p in str(value).split(",") if p.strip()]


def _check_recipients(addrs: list[str], allowed_domains: list[str]) -> list[str]:
    allowed = [str(d).strip().lower().lstrip("@").rstrip(".") for d in allowed_domains or [] if str(d).strip()]
    out: list[str] = []
    for addr in addrs:
        m = _ADDR_RE.match(addr)
        if not m:
            raise ValueError(f"send_email: invalid recipient address {addr!r}")
        domain = m.group(1).lower().rstrip(".")
        if allowed and not any(domain == d or domain.endswith("." + d) for d in allowed):
            raise ValueError(
                f"send_email: recipient domain {domain!r} is not in allowed_recipient_domains"
            )
        out.append(addr)
    return out


def _as_dict(value: Any) -> dict[str, Any]:
    from app.core.nodes.payload import unwrap_payload, wrapper_field

    if wrapper_field(value) is not None:
        # F19 (F-06): read the payload (CodeResult.data, …), not the wrapper.
        value = unwrap_payload(value)
        if isinstance(value, str):
            return {"body": value}
        if not isinstance(value, dict):
            import json as _json
            return {"body": _json.dumps(value, default=str)[:8000]}
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return value.model_dump()
    text = getattr(value, "text", None) or getattr(value, "content", None)
    if text is not None:
        return {"body": str(text)}
    return {"body": str(value)}


class SendEmailNode(Node):
    """Send outbound email using platform SMTP env (GRAPHYN_SMTP_*)."""

    node_type: ClassVar[str] = "send_email"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="send_email",
        label="Send Email",
        description=(
            "Outbound SMTP email via GRAPHYN_SMTP_* env. "
            "Supports dry_run / GRAPHYN_SMTP_DRY_RUN. Not IMAP/inbox."
        ),
        category="Output",
        version="0.1.0",
        tags=["email", "smtp", "notify", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=False,
        cacheable=False,
        idempotent=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=object | None,
            required=False,
            description="dict with subject/body (or text/content) or any object coerced to body; to/from are honoured only when allow_payload_recipients=true",
        ),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=EmailReceipt, description="EmailReceipt"),
    }

    class Config(NodeConfig):
        to: str = Field(default="", title="To", description="Recipient email(s), comma-separated.")
        allowed_recipient_domains: list[str] = Field(
            default_factory=list,
            title="Allowed recipient domains",
            description="If non-empty, every recipient must be in one of these domains (subdomains allowed).",
        )
        allow_payload_recipients: bool = Field(
            default=False,
            title="Allow payload recipients",
            description="Use to/from from the input payload when config `to` is empty. Default false: upstream data (e.g. LLM output) cannot choose recipients.",
        )
        subject: str = Field(default="Graphyn notification", title="Subject", description="Email subject.")
        body_template: str = Field(default="", title="Body template", description="Optional body override.")
        from_addr: str = Field(default="", title="From", description="Override From address.")
        dry_run: bool = Field(default=False, title="Dry run", description="Skip SMTP dial; return receipt.")
        connection_id: str = Field(
            default="",
            title="Credential connection id",
            description="SMTP credential connection id. Empty → workspace default → GRAPHYN_SMTP_* env.",
        )

    @classmethod
    def missing_run_config(cls, config):
        if not str(getattr(config, "to", "") or "").strip() and not bool(getattr(config, "allow_payload_recipients", False)):
            return [("to", "send_email: recipient 'to' is required (or enable allow_payload_recipients).")]
        return []

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        raw = inputs.get("input", inputs)
        data = _as_dict(raw)
        allow_payload = bool(getattr(self.config, "allow_payload_recipients", False))
        to_list = _split_addrs(getattr(self.config, "to", "") or "")
        if not to_list and allow_payload:
            to_list = _split_addrs(data.get("to") or data.get("recipient"))
        elif not to_list and (data.get("to") or data.get("recipient")):
            raise ValueError(
                "send_email: payload supplies recipients but allow_payload_recipients=false; "
                "set config `to` or opt in explicitly."
            )
        to_list = _check_recipients(to_list, list(getattr(self.config, "allowed_recipient_domains", []) or []))
        subject = (getattr(self.config, "subject", "") or data.get("subject") or "Graphyn notification").strip()
        body = (getattr(self.config, "body_template", "") or "").strip()
        if not body:
            body = str(data.get("body") or data.get("text") or data.get("content") or data.get("message") or "")
            if not body and data:
                # last resort: compact payload
                try:
                    import json
                    body = json.dumps(data, default=str)[:8000]
                except Exception:
                    body = str(data)[:8000]
        from_addr = (getattr(self.config, "from_addr", "") or "").strip()
        if not from_addr and allow_payload:
            from_addr = str(data.get("from") or data.get("from_addr") or "").strip()
        if from_addr and not _ADDR_RE.match(from_addr):
            raise ValueError(f"send_email: invalid from address {from_addr!r}")
        dry_run = bool(getattr(self.config, "dry_run", False))

        from app.core.notify.smtp_notify import send_email

        conn_id = (getattr(self.config, "connection_id", "") or "") or None
        t0 = time.monotonic()
        req_hash = self.body_sha256({"to": to_list, "subject": subject, "body": body})
        try:
            receipt = send_email(
                to=to_list,
                subject=subject,
                body=body,
                from_addr=from_addr or None,
                dry_run=dry_run if dry_run else None,
                connection_id=conn_id,
            )
        except Exception as exc:
            if "needs-credentials" not in str(exc):
                self.record_external_call("smtp", "SEND", self._relay_label(conn_id), None,
                                          request_sha256=req_hash,
                                          duration_ms=(time.monotonic() - t0) * 1000.0,
                                          connection_id=conn_id, error=type(exc).__name__)
            raise
        if not receipt.get("dry_run"):
            self.record_external_call("smtp", "SEND", self._relay_label(conn_id), "sent",
                                      request_sha256=req_hash,
                                      duration_ms=(time.monotonic() - t0) * 1000.0,
                                      connection_id=receipt.get("connection_id") or conn_id)
        return {
            "output": EmailReceipt(
                ok=bool(receipt.get("ok")),
                dry_run=bool(receipt.get("dry_run")),
                to=list(receipt.get("to") or []),
                from_addr=str(receipt.get("from_addr") or ""),
                subject=str(receipt.get("subject") or ""),
                message=str(receipt.get("message") or ""),
                metadata={"provider": "smtp"},
            )
        }

    @staticmethod
    def _relay_label(connection_id: str | None) -> str:
        """``smtp://host:port`` of the configured relay (no credentials)."""
        try:
            from app.core.notify.smtp_notify import smtp_config_from_credentials

            cfg = smtp_config_from_credentials(connection_id=connection_id)
            host = str(cfg.get("host") or "unknown")
            port = cfg.get("port")
            return f"smtp://{host}:{port}" if port else f"smtp://{host}"
        except Exception:
            return "smtp://unknown"
