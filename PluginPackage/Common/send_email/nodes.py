"""SendEmailNode — outbound SMTP via GRAPHYN_SMTP_* (dry-run capable)."""
from __future__ import annotations

import importlib
import logging
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


def _as_dict(value: Any) -> dict[str, Any]:
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
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=object | None,
            required=False,
            description="dict with to/subject/body (or text/content) or any object coerced to body",
        ),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="EmailReceipt"),
    }

    class Config(NodeConfig):
        to: str = Field(default="", title="To", description="Recipient email(s), comma-separated.")
        subject: str = Field(default="Graphyn notification", title="Subject", description="Email subject.")
        body_template: str = Field(default="", title="Body template", description="Optional body override.")
        from_addr: str = Field(default="", title="From", description="Override From address.")
        dry_run: bool = Field(default=False, title="Dry run", description="Skip SMTP dial; return receipt.")
        connection_id: str = Field(
            default="",
            title="Credential connection id",
            description="SMTP credential connection id. Empty → workspace default → GRAPHYN_SMTP_* env.",
        )

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        raw = inputs.get("input", inputs)
        data = _as_dict(raw)
        to = (getattr(self.config, "to", "") or data.get("to") or data.get("recipient") or "").strip()
        if isinstance(to, list):
            to_list = [str(x).strip() for x in to if str(x).strip()]
        else:
            to_list = [p.strip() for p in str(to).split(",") if p.strip()]
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
        from_addr = (getattr(self.config, "from_addr", "") or data.get("from") or data.get("from_addr") or "").strip()
        dry_run = bool(getattr(self.config, "dry_run", False))

        from app.core.smtp_notify import send_email

        receipt = send_email(
            to=to_list,
            subject=subject,
            body=body,
            from_addr=from_addr or None,
            dry_run=dry_run if dry_run else None,
            connection_id=(getattr(self.config, "connection_id", "") or "") or None,
        )
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
