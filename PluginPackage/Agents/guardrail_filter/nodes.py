"""GuardrailFilterNode — PII/jailbreak/toxicity guardrails

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import re

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
        _types = importlib.import_module("guardrail_filter.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

GuardrailHit = _types.GuardrailHit

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


DEFAULT_POLICIES = ("pii", "secret")
VALID_ACTIONS = ("block", "redact", "flag")
REDACTION = "[redacted]"

# All rules are compiled with the SAME flags for detection and redaction.
RULES: dict[str, re.Pattern[str]] = {
    "pii": re.compile(
        r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"          # email
        r"|\b\d{3}-\d{2}-\d{4}\b",                       # US SSN
        re.I,
    ),
    "secret": re.compile(
        r"\bsk-[A-Za-z0-9_-]{12,}"                        # OpenAI/Anthropic-style keys
        r"|\bAKIA[0-9A-Z]{16}\b"                          # AWS access key id
        r"|\bgh[pousr]_[A-Za-z0-9]{20,}"                   # GitHub tokens
        r"|\bxox[abpr]-[A-Za-z0-9-]{10,}"                  # Slack tokens
        r"|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
        re.I,
    ),
    "profanity": re.compile(r"\b(damn|hell)\b", re.I),
    "jailbreak": re.compile(
        r"\bignore (?:all |any )?(?:previous|prior|above) (?:instructions|prompts)\b"
        r"|\bdisregard (?:the |your )?(?:system|previous) (?:prompt|instructions)\b",
        re.I,
    ),
}


def _iter_strings(obj: Any):
    """Yield every string reachable in *obj* (dicts, lists, tuples, models)."""
    obj = _dump(obj)
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, bytes):
        yield obj.decode("utf-8", errors="replace")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
            yield from _iter_strings(v)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            yield from _iter_strings(item)


def _redact(obj: Any, patterns: list[re.Pattern[str]]) -> Any:
    """Return a copy of *obj* with every active pattern redacted, preserving structure."""
    if hasattr(obj, "model_dump") and hasattr(type(obj), "model_validate"):
        data = _redact(obj.model_dump(), patterns)
        try:
            return type(obj).model_validate(data)
        except Exception:
            return data
    if isinstance(obj, str):
        for pat in patterns:
            obj = pat.sub(REDACTION, obj)
        return obj
    if isinstance(obj, bytes):
        return _redact(obj.decode("utf-8", errors="replace"), patterns)
    if isinstance(obj, dict):
        return {(_redact(k, patterns) if isinstance(k, str) else k): _redact(v, patterns) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x, patterns) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_redact(x, patterns) for x in obj)
    return obj


def _guardrail(config, inputs, types) -> dict:
    payload = inputs.get("input")
    policies = [str(p) for p in (config.policies or [])] or list(DEFAULT_POLICIES)
    unknown = [p for p in policies if p not in RULES]
    if unknown:
        raise ValueError(f"guardrail_filter: unknown policies {unknown}; known: {sorted(RULES)}")
    action = str(config.action or "")
    if action not in VALID_ACTIONS:
        log.warning("guardrail_filter: unknown action %r — failing closed (block)", action)
        action = "block"

    strings = list(_iter_strings(payload))
    hits = []
    active: list[re.Pattern[str]] = []
    for policy in policies:
        pat = RULES[policy]
        count = sum(len(pat.findall(s)) for s in strings)
        if count:
            active.append(pat)
            hits.append(_T(types, "GuardrailHit", rule=policy, severity=action, score=float(count)))

    if hits and action == "block":
        raise RuntimeError(
            "guardrail_filter blocked input: " + ",".join(getattr(h, "rule", "rule") for h in hits)
        )
    output = _redact(payload, active) if hits and action == "redact" else payload
    return {"output": output, "violations": hits}



class GuardrailFilterNode(Node):
    """PII/jailbreak/toxicity guardrails"""

    node_type: ClassVar[str] = "guardrail_filter"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="guardrail_filter",
        label="Guardrail Filter",
        description="PII/jailbreak/toxicity guardrails",
        category="Quality",
        version="0.1.0",
        tags=["agents"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="Any"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="Any"),
        "violations": OutputPort(name="violations", data_type=object, description="list[GuardrailHit] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        policies: list = Field(
            default_factory=lambda: list(DEFAULT_POLICIES),
            title="Policies",
            description="Rules to apply: pii, secret, profanity, jailbreak. Empty → pii+secret.",
        )
        action: Literal["block", "redact", "flag"] = Field(
            default="block",
            title="Action",
            description="block (raise), redact (mask matches, keep structure) or flag (pass through + violations).",
        )

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'agents' / 'guardrail_filter'
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
            result = {
                "output": None,
                "violations": [],
            }
            return result
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"guardrail_filter: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return _guardrail(self.config, inputs, _types)
