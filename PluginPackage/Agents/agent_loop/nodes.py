"""AgentLoopNode — extractive (no-LLM) goal/context loop.

This node does NOT call a model or any tools. ``model``, ``api_secret_name``
and ``tool_allowlist`` are reserved for a future LLM mode and are ignored.
Use ``llm_chat`` for model calls.

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json
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
        _types = importlib.import_module("agent_loop.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

AgentResult = _types.AgentResult

log = logging.getLogger(__name__)

def _T(types: Any, name: str, **kwargs: Any) -> Any:
    cls = getattr(types, name, None) if types is not None else None
    if cls is None:
        return kwargs
    fields = getattr(cls, "model_fields", None)
    if isinstance(fields, dict) and fields:
        kwargs = {k: v for k, v in kwargs.items() if k in fields}
    return cls(**kwargs)

def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj

def _text(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, list):
        return "\n".join(_text(x) for x in obj)
    data = _dump(obj)
    if isinstance(data, dict):
        for key in ("text", "query", "content", "answer", "user", "path", "value", "final"):
            if data.get(key):
                return str(data[key])
        return json.dumps(data, default=str)
    return str(obj)

def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())

def _agent_loop(config, inputs, types):
    """Extractive, deterministic loop: scans the context in windows until the
    goal's terms are covered. No LLM is called and no tools are invoked."""
    goal = _text(inputs.get("goal") or inputs.get("input"))
    context = _text(inputs.get("context"))
    steps_n = max(1, int(config.max_steps))
    if (config.tool_allowlist or []):
        log.info("agent_loop: tool_allowlist is ignored in extractive mode (no tools are called)")
    steps = []
    working = context
    for i in range(steps_n):
        observation = working[:500]
        if goal and observation and set(_tokens(goal)) <= set(_tokens(observation)):
            steps.append({"step": i, "action": "finish", "observation": "goal terms covered"})
            break
        steps.append({"step": i, "action": "read_context", "observation": observation[:240]})
        if not working:
            break
        working = working[240:]
    final = goal if not context else f"{goal}\n\nFrom context: {context[:800]}"
    return _T(
        types,
        "AgentResult",
        final=final.strip(),
        steps=steps,
        mode="extractive",
        metadata={"mode": "extractive", "model": None, "llm_called": False, "tools_called": []},
    )



class AgentLoopNode(Node):
    """Extractive (no-LLM) goal/context loop — see module docstring."""

    node_type: ClassVar[str] = "agent_loop"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="agent_loop",
        label="Agent Loop",
        description=(
            "Extractive agent loop (no LLM, no tool calls): scans context for the goal's "
            "terms and returns goal + context excerpt. Output mode='extractive'."
        ),
        category="Agents",
        version="0.1.0",
        tags=["agents"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "goal": InputPort(name="goal", data_type=object, required=True, description="str"),
        "context": InputPort(name="context", data_type=object | None, required=False, description="Any optional"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="AgentResult NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        max_steps: int = Field(default=8, ge=1, title="Max steps", description="Maximum context windows to scan.")
        model: str = Field(default="gpt-4o-mini", title="Model", description="Reserved — ignored (extractive mode calls no model).")
        api_secret_name: str = Field(default="OPENAI_API_KEY", title="Api secret name", description="Reserved — ignored (extractive mode calls no model).")
        tool_allowlist: list = Field(default_factory=list, title="Tool allowlist", description="Reserved — ignored (extractive mode calls no tools).")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'agents' / 'agent_loop'
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
            result = AgentResult()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"agent_loop: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _agent_loop(self.config, inputs, _types)}
