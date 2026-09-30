"""RagUrlCrawlNode — URL crawl for RAG ingest

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import re

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
        _types = importlib.import_module("rag_url_crawl.types")
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

def _url_crawl(config, inputs, types):
    from urllib.parse import urljoin, urlparse
    from app.core.trust.egress import validate_http_egress_url

    urls = list(_cfg(config, "urls", []) or [])
    max_pages = int(_cfg(config, "max_pages", 5) or 5)
    same_host = bool(_cfg(config, "same_host_only", True))
    docs = []
    seen: set[str] = set()
    queue = list(urls)
    try:
        import httpx
    except ImportError as exc:
        raise ImportError("rag_url_crawl requires httpx") from exc
    with httpx.Client(follow_redirects=False, timeout=20.0) as client:
        while queue and len(docs) < max_pages:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            validate_http_egress_url(url)
            response = client.get(url)
            if response.status_code in (301, 302, 303, 307, 308):
                loc = response.headers.get("location")
                if loc:
                    queue.append(urljoin(url, loc))
                continue
            response.raise_for_status()
            text = re.sub(r"<[^>]+>", " ", response.text)
            text = re.sub(r"\s+", " ", text).strip()
            docs.append(_T(types, "RawDocument", path=url, text=text[:20000], metadata={"status": response.status_code}))
            if same_host:
                host = urlparse(url).netloc
                for href in re.findall(r'href=["\']([^"\']+)["\']', response.text):
                    nxt = urljoin(url, href)
                    if urlparse(nxt).netloc == host:
                        queue.append(nxt)
    return docs



class RagUrlCrawlNode(Node):
    """URL crawl for RAG ingest"""

    node_type: ClassVar[str] = "rag_url_crawl"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="rag_url_crawl",
        label="Rag Url Crawl",
        description="URL crawl for RAG ingest",
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
        urls: list = Field(default_factory=lambda: [])
        max_pages: int = Field(default=20, title="Max pages", description="Max pages.")
        same_host_only: bool = Field(default=True, title="Same host only", description="Same host only.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'rag' / 'rag_url_crawl'
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
            raise ImportError(f"rag_url_crawl: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _url_crawl(self.config, inputs, _types)}
