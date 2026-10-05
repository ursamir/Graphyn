"""WebhookTriggerNode — source node for inbound webhooks.

The API endpoint ``POST /api/v1/hooks/{workspace}/{pipeline}`` authenticates
the caller (HMAC signature or bearer token), then starts the pipeline with
``input_overrides={<this node id>: {"body": …, "headers": …, "query": …}}``.
This node only passes those values through (headers re-filtered by an
optional allowlist). Manual runs (no payload) emit ``sample_body`` and empty
headers / query, so a graph can be tested from the console.

No secrets live in this node's config: the signing secret is a credential
connection (kind ``inbound_webhook``) referenced by the pipeline hook settings.
"""
from __future__ import annotations

import logging
from typing import Any, ClassVar

from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

log = logging.getLogger(__name__)


def _str_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}


class WebhookTriggerNode(Node):
    node_type: ClassVar[str] = "webhook_trigger"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="webhook_trigger",
        label="Webhook Trigger",
        description=(
            "Source node for inbound webhooks. Emits the request body (JSON), "
            "allow-listed headers and query parameters injected by the hooks API."
        ),
        category="Input",
        version="1.0.0",
        tags=["webhook", "trigger", "workflow", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
    )
    # Optional inputs: supplied only via run input_overrides (never wired).
    input_ports: ClassVar[dict[str, InputPort]] = {
        "body": InputPort(name="body", data_type=object | None, required=False, description="Webhook JSON body (injected)"),
        "headers": InputPort(name="headers", data_type=object | None, required=False, description="Allow-listed headers (injected)"),
        "query": InputPort(name="query", data_type=object | None, required=False, description="Query parameters (injected)"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "body": OutputPort(name="body", data_type=object, description="Request body (parsed JSON)"),
        "headers": OutputPort(name="headers", data_type=object, description="Allow-listed request headers"),
        "query": OutputPort(name="query", data_type=object, description="Query string parameters"),
    }

    class Config(NodeConfig):
        header_allowlist: list = Field(
            default_factory=list,
            title="Header allowlist",
            description="When set, keep only these lower-case header names (empty = keep what the API passed).",
        )
        sample_body: dict = Field(
            default_factory=dict,
            title="Sample body",
            description="Body emitted on manual runs (no webhook payload). Never put secrets here.",
        )

    def process(self, inputs=None, **kwargs):
        inputs = inputs if isinstance(inputs, dict) else dict(kwargs)
        body = inputs.get("body")
        if body is None:
            body = dict(self.config.sample_body or {})
        headers = _str_map(inputs.get("headers"))
        allow = {str(h).strip().lower() for h in (self.config.header_allowlist or []) if str(h).strip()}
        if allow:
            headers = {k: v for k, v in headers.items() if k.lower() in allow}
        return {"body": body, "headers": headers, "query": _str_map(inputs.get("query"))}
