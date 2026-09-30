"""RagSlackConnectorNode — Slack history connector (secret)

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any
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
        _types = importlib.import_module("rag_slack_connector.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

RawDocument = _types.RawDocument

log = logging.getLogger(__name__)

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

def _T(types: Any, name: str, **kwargs: Any) -> Any:
    cls = getattr(types, name, None) if types is not None else None
    if cls is None:
        return kwargs
    fields = getattr(cls, "model_fields", None)
    if isinstance(fields, dict) and fields:
        kwargs = {k: v for k, v in kwargs.items() if k in fields}
    return cls(**kwargs)

def _notion_or_slack(config, inputs, types, kind: str):
    secret = str(_cfg(config, "secret_name", "") or "")
    # Guarded: secret store, then env only for secret-shaped non-GRAPHYN_ names.
    from app.core.trust.secrets import resolve_secret
    token = resolve_secret(secret) if secret else ""
    if not token:
        raise RuntimeError(
            f"{kind} connector requires env/secret {secret or '(unset secret_name)'} — refusing to invent documents."
        )
    # Token is present: record a real fetch attempt via the public API shape.
    if kind == "notion":
        import httpx
        from app.core.trust.egress import validate_http_egress_url

        db = str(_cfg(config, "database_id", "") or "")
        url = f"https://api.notion.com/v1/databases/{db}/query" if db else "https://api.notion.com/v1/search"
        validate_http_egress_url(url)
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers={"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"}, json={})
        response.raise_for_status()
        payload = response.json()
        docs = []
        for item in payload.get("results") or []:
            docs.append(_T(types, "RawDocument", path=str(item.get("id") or ""), text=json.dumps(item)[:8000], metadata={"source": "notion"}))
        return docs
    import httpx
    from app.core.trust.egress import validate_http_egress_url

    channels = _cfg(config, "channel_ids", []) or []
    docs = []
    with httpx.Client(timeout=30.0) as client:
        for channel in channels:
            url = "https://slack.com/api/conversations.history"
            validate_http_egress_url(url)
            response = client.get(url, headers={"Authorization": f"Bearer {token}"}, params={"channel": channel, "limit": 50})
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise RuntimeError(f"slack API error: {payload.get('error')}")
            for msg in payload.get("messages") or []:
                docs.append(_T(types, "RawDocument", path=str(msg.get("ts") or ""), text=str(msg.get("text") or ""), metadata={"channel": channel}))
    return docs

def _impl(config, inputs, types):
    return _notion_or_slack(config, inputs, types, "slack")



class RagSlackConnectorNode(Node):
    """Slack history connector (secret)"""

    node_type: ClassVar[str] = "rag_slack_connector"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="rag_slack_connector",
        label="Rag Slack Connector",
        description="Slack history connector (secret)",
        category="Input",
        version="0.1.0",
        tags=["rag"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {}

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[RawDocument] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        secret_name: str = Field(default='SLACK_BOT_TOKEN', title="Secret name", description="Secret name.")
        channel_ids: list = Field(default_factory=lambda: [])

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'rag' / 'rag_slack_connector'
        if stub:
            log.warning(
                "%s: stub mode (config.stub=True) returned a placeholder, not a real result",
                getattr(self, "node_type", type(self).__name__),
            )
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            _out = out_dir / 'stub'
            result = []
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"rag_slack_connector: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _impl(self.config, inputs, _types)}
