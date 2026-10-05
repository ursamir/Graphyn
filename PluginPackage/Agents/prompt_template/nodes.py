"""PromptTemplateNode — Jinja/f-string prompt render

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json
import re
import string

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any, Literal
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
        _types = importlib.import_module("prompt_template.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

log = logging.getLogger(__name__)

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


class _SafeFormatter(string.Formatter):
    """str.format semantics, but no private/dunder attribute traversal and a
    clear error on missing keys."""

    def get_field(self, field_name, args, kwargs):
        for part in re.split(r"[.\[\]]", field_name):
            if part.startswith("_"):
                raise ValueError(f"prompt_template: private attribute access {field_name!r} is not allowed")
        return super().get_field(field_name, args, kwargs)

    def get_value(self, key, args, kwargs):
        if isinstance(key, int):
            raise ValueError("prompt_template: positional fields ('{}' / '{0}') are not supported; use names")
        if key not in kwargs:
            raise ValueError(
                f"prompt_template: missing variable {key!r} (available: {sorted(kwargs)})"
            )
        return kwargs[key]


_SIMPLE_VAR = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*\}\}")


def _render_simple_jinja(template: str, variables: dict) -> str:
    """Fallback when jinja2 is unavailable: ``{{ var }}`` / ``{{ a.b }}`` only."""
    if "{%" in template or "{#" in template:
        raise ImportError("jinja2 is required for {% %} / {# #} blocks (pip install jinja2)")

    def _sub(m: re.Match) -> str:
        cur: Any = variables
        path = m.group(1)
        for part in path.split("."):
            if part.startswith("_"):
                raise ValueError(f"prompt_template: private attribute access {path!r} is not allowed")
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif not isinstance(cur, dict) and hasattr(cur, part):
                cur = getattr(cur, part)
            else:
                raise ValueError(f"prompt_template: undefined variable {path!r}")
        return "" if cur is None else str(cur)

    return _SIMPLE_VAR.sub(_sub, template)


def _render_jinja(template: str, variables: dict) -> str:
    try:
        from jinja2 import StrictUndefined
        from jinja2.exceptions import UndefinedError
        from jinja2.sandbox import SandboxedEnvironment
    except ImportError:
        return _render_simple_jinja(template, variables)
    env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)
    try:
        return env.from_string(template).render(**variables)
    except UndefinedError as exc:
        raise ValueError(f"prompt_template: undefined variable ({exc})") from exc


def _variables(inputs: dict) -> dict:
    raw = inputs.get("variables")
    if raw is None:
        raw = inputs.get("input")
    data = _dump(raw)
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {"input": _text(raw)}
    out = {}
    for k, v in data.items():
        out[str(k)] = _text(v) if hasattr(v, "model_dump") else v
    return out


def _prompt_template(config, inputs, types) -> str:
    template = str(config.template or "")
    engine = str(config.engine or "format")
    variables = _variables(inputs)
    if not template:
        # No template: pass the single input through as text.
        return _text(variables.get("input", variables)) if variables else ""
    if engine in ("format", "fstring"):
        return _SafeFormatter().vformat(template, (), variables)
    if engine == "jinja":
        return _render_jinja(template, variables)
    raise ValueError(f"prompt_template: unknown engine {engine!r} (use 'format' or 'jinja')")



class PromptTemplateNode(Node):
    """Jinja/f-string prompt render"""

    node_type: ClassVar[str] = "prompt_template"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="prompt_template",
        label="Prompt Template",
        description="Prompt render: str.format ('format') or sandboxed Jinja2 ('jinja')",
        category="Transform",
        version="0.1.0",
        tags=["agents"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "variables": InputPort(name="variables", data_type=object | None, required=False, description="dict of template variables"),
        "input": InputPort(name="input", data_type=object | None, required=False, description="Alternate input (linear chains); dict or value bound as {input}"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="str"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        template: str = Field(default="", title="Template", description="Prompt template. Empty → pass the input through as text.")
        engine: Literal["format", "jinja", "fstring"] = Field(
            default="format",
            title="Engine",
            description="format: str.format '{name}'; jinja: sandboxed Jinja2 '{{ name }}' (strict undefined); fstring: alias of format.",
        )

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'agents' / 'prompt_template'
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
            result = ""
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"prompt_template: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _prompt_template(self.config, inputs, _types)}
