"""AgentLoopNode — LLM-driven agent loop with optional Graphyn MCP tools.

Each step asks a chat model (Ollama, OpenAI-compatible, Anthropic or Gemini
via ``app.core.ml.llm_client``) for a JSON decision:

    {"action": "call_tool", "tool": "<name>", "arguments": {...}}
    {"action": "final", "answer": "<text>"}

``call_tool`` runs an allowlisted Graphyn MCP tool in-process (read-only
unless ``allow_mutating=True``; authenticated with a ``graphyn_mcp``
credential when the platform requires auth) and feeds the result back as an
observation. The loop stops on ``final`` or after ``max_steps`` (then the
model is asked once more for a final answer from its observations). Every
model call is recorded via ``record_external_call``.
"""
from __future__ import annotations

import importlib
import json
import logging
import re
import threading
import time
from typing import Any, ClassVar, Literal

from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:  # canonical inter-node payload contract (F-06)
    from app.core.nodes.payload import unwrap_payload as _unwrap_payload, wrapper_field as _wrapper_field

    def _unwrap(v):
        """Unwrap known wrappers (python_code / csv_table / http_request …); keep typed inputs as-is."""
        return _unwrap_payload(v) if _wrapper_field(v) is not None else v
except Exception:  # pragma: no cover - older core
    def _unwrap(v):
        return v


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

_MCP_KIND = "graphyn_mcp"

# Tools that change platform state / touch credentials / execute work.
_MUTATING_PREFIXES: tuple[str, ...] = (
    "create_", "update_", "delete_", "remove_", "revoke_", "promote_", "approve_",
    "accept_", "reject_", "install_", "uninstall_", "manage_", "put_", "post_",
    "upsert_", "enable_", "disable_", "publish_", "rollback_", "cancel_", "pause_",
    "resume_", "replay_", "run_", "execute_", "register_", "request_", "save_",
    "upload_", "download_", "mark_", "materialize_", "instantiate_", "test_",
    "set_", "write_", "send_", "export_", "import_", "propose_",
)
_MUTATING_EXACT = frozenset({"get_credential", "optimize_execution", "decide_gate"})


def _is_mutating(name: str) -> bool:
    return name in _MUTATING_EXACT or name.startswith(_MUTATING_PREFIXES)


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
        for key in ("text", "content", "query", "goal", "prompt", "answer", "final", "value"):
            if isinstance(data.get(key), str) and data.get(key):
                return str(data[key])
        return json.dumps(data, default=str)
    return str(obj)


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def parse_decision(content: str) -> dict[str, Any] | None:
    """Extract the first JSON object with an ``action`` key from model output."""
    text = _THINK.sub("", content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                    except (ValueError, TypeError):
                        break
                    if isinstance(obj, dict) and obj.get("action"):
                        return obj
                    break
        start = text.find("{", start + 1)
    return None


def _mcp_token(connection_id: str) -> str | None:
    from app.core.config import api_token, auth_required
    from app.core.trust.identity import token_auth_configured

    if not (api_token() or token_auth_configured() or auth_required()):
        return None
    from app.core.credentials.resolve import NeedsCredentialsError, resolve_connection

    try:
        resolved = resolve_connection(kind=_MCP_KIND, connection_id=(connection_id or None), required=True)
    except NeedsCredentialsError as exc:
        raise NeedsCredentialsError(
            "agent_loop: tool_allowlist is set and the platform requires auth — set "
            "config.mcp_connection_id to a credential of kind 'graphyn_mcp' (agent token). "
            f"({exc})"
        ) from exc
    except Exception as exc:  # unknown kind (mcp-tool-call plugin not loaded)
        raise RuntimeError(
            "agent_loop: credential kind 'graphyn_mcp' is unavailable — install the "
            f"mcp-tool-call plugin to register it ({exc})."
        ) from exc
    token = str((resolved.get("payload") or {}).get("token") or "")
    if not token:
        raise RuntimeError("agent_loop: graphyn_mcp credential has no token")
    return token


def _call_tool(name: str, args: dict, *, token: str | None, timeout_s: float) -> dict[str, Any]:
    """Run one MCP tool handler in-process with auth + timeout; return a result dict."""
    from app.mcp.auth import check_auth
    from app.mcp.server import get_tool

    call_args = dict(args)
    if token:
        call_args["_meta"] = {"auth_token": token}
    err = check_auth(call_args, tool_name=name)
    if err is not None:
        return {"ok": False, "error": str(err.get("message") or "unauthorized")}
    tool = get_tool(name)
    if tool is None:
        return {"ok": False, "error": f"unknown tool {name!r}"}
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["result"] = tool["handler"](call_args)
        except BaseException as exc:  # noqa: BLE001 — reported as observation
            box["error"] = f"{type(exc).__name__}: {exc}"

    th = threading.Thread(target=_target, name=f"agent_loop:{name}", daemon=True)
    th.start()
    th.join(timeout_s if timeout_s > 0 else None)
    if th.is_alive():
        return {"ok": False, "error": f"tool {name!r} exceeded timeout_s={timeout_s}"}
    if "error" in box:
        return {"ok": False, "error": box["error"]}
    result = box.get("result")
    if isinstance(result, dict) and result.get("error") is True:
        return {"ok": False, "error": str(result.get("message") or "tool error"), "result": result}
    return {"ok": True, "result": result}


def _tool_catalog(names: list[str]) -> list[dict[str, str]]:
    from app.mcp.server import get_tool

    out = []
    for n in names:
        tool = get_tool(n)
        if tool is None:
            raise ValueError(f"agent_loop: tool_allowlist names unknown MCP tool {n!r}")
        desc = str(tool.get("description") or "")[:300]
        schema = tool.get("input_schema") or tool.get("inputSchema") or {}
        props = sorted((schema.get("properties") or {}).keys()) if isinstance(schema, dict) else []
        out.append({"name": n, "description": desc, "arguments": ", ".join(p for p in props if p != "_meta")})
    return out


class AgentLoopNode(Node):
    """LLM agent loop with optional allowlisted Graphyn MCP tool calls."""

    node_type: ClassVar[str] = "agent_loop"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="agent_loop",
        label="Agent Loop",
        description=(
            "LLM agent loop: the model decides each step (call an allowlisted Graphyn "
            "MCP tool or answer). Providers: ollama (local), openai_compat, anthropic, gemini."
        ),
        category="Agents",
        version="1.0.0",
        tags=["agents", "llm", "mcp"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=False,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "goal": InputPort(name="goal", data_type=object | None, required=False, description="Goal / task (str or message object)"),
        "context": InputPort(name="context", data_type=object | None, required=False, description="Optional context"),
        "input": InputPort(name="input", data_type=object | None, required=False, description="Alternate goal input for linear chains"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="AgentResult (final answer + step trace)"),
    }

    class Config(NodeConfig):
        provider: Literal["ollama", "openai_compat", "anthropic", "gemini"] = Field(
            default="ollama", title="Provider",
            description="Chat model provider. ollama runs locally (OLLAMA_BASE_URL); others need a credential.")
        model: str = Field(default="", title="Model", description="Model id. Empty → OLLAMA_MODEL for ollama, gpt-4o-mini otherwise.")
        base_url: str = Field(default="", title="Base URL", description="Optional OpenAI-compatible base URL override.")
        api_secret_name: str = Field(default="OPENAI_API_KEY", title="API secret name", description="Secret/env NAME for openai_compat (never the key itself).")
        connection_id: str = Field(default="", title="LLM credential connection id", description="Credential store connection for the model provider. Empty → workspace default → env.")
        temperature: float = Field(default=0.0, ge=0, title="Temperature", description="Sampling temperature.")
        timeout_s: float = Field(default=120.0, gt=0, title="Timeout (s)", description="Per model call / tool call timeout.")
        max_steps: int = Field(default=4, ge=1, le=20, title="Max steps", description="Maximum decide/act iterations before forcing a final answer.")
        system_prompt: str = Field(default="", title="System prompt", description="Extra instructions prepended to the agent protocol.")
        tool_allowlist: list = Field(default_factory=list, title="Tool allowlist", description="Graphyn MCP tools the agent may call (empty → answer without tools).")
        allow_mutating: bool = Field(default=False, title="Allow mutating", description="Permit state-changing tools (they must still be allowlisted).")
        mcp_connection_id: str = Field(default="", title="MCP credential connection id", description="graphyn_mcp credential used for tool calls when the platform requires auth.")
        require_tool_call: bool = Field(default=False, title="Require a tool call", description="When tools are allowlisted, reject a final answer given before any tool was called (the model is told to use a tool first).")

    # ── LLM call ─────────────────────────────────────────────────────────────
    def _chat(self, messages: list[dict[str, str]]) -> str:
        from app.core.ml.llm_client import chat_completion

        provider = str(self.config.provider)
        model = (self.config.model or "").strip()
        if not model:
            import os

            model = (os.environ.get("OLLAMA_MODEL") or "qwen3:0.6b") if provider == "ollama" else "gpt-4o-mini"
        conn = (self.config.connection_id or "").strip() or None
        req_hash = self.body_sha256({"model": model, "messages": messages})
        t0 = time.monotonic()
        try:
            result = chat_completion(
                messages=messages, provider=provider, model=model,
                temperature=float(self.config.temperature),
                base_url=(self.config.base_url or "").strip() or None,
                api_secret_name=self.config.api_secret_name or "OPENAI_API_KEY",
                connection_id=conn, timeout_s=float(self.config.timeout_s),
            )
        except Exception as exc:
            self.record_external_call("llm", "POST", self.config.base_url or f"llm://{provider}", None,
                                      request_sha256=req_hash, duration_ms=(time.monotonic() - t0) * 1000.0,
                                      connection_id=conn, error=type(exc).__name__)
            raise RuntimeError(f"agent_loop: provider={provider!r} model={model!r} failed: {exc}") from exc
        content = str(result.get("content") or "")
        self.record_external_call("llm", "POST", str(result.get("base_url") or f"llm://{provider}"), 200,
                                  request_sha256=req_hash, response_sha256=content,
                                  duration_ms=(time.monotonic() - t0) * 1000.0, connection_id=conn)
        self._model_used = str(result.get("model") or model)
        return content

    def _protocol(self, tools: list[dict[str, str]]) -> str:
        lines = [
            "You are an agent that completes the user's goal step by step.",
            "Reply with exactly ONE JSON object and nothing else.",
        ]
        if tools:
            lines.append('To use a tool: {"action": "call_tool", "tool": "<name>", "arguments": {...}}')
            lines.append("Use a tool whenever the goal needs facts about the Graphyn platform; never invent them.")
            lines.append("Available tools:")
            for t in tools:
                lines.append(f"- {t['name']}({t['arguments']}): {t['description']}")
        lines.append('To finish: {"action": "final", "answer": "<your answer>"}')
        extra = (self.config.system_prompt or "").strip()
        if extra:
            lines.insert(0, extra)
        return "\n".join(lines)

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        goal = _text(_unwrap(inputs.get("goal"))) or _text(_unwrap(inputs.get("input")))
        if not goal.strip():
            raise ValueError("agent_loop: a goal is required (goal or input port)")
        context = _text(_unwrap(inputs.get("context")))

        allow = [str(t).strip() for t in (self.config.tool_allowlist or []) if str(t).strip()]
        for name in allow:
            if _is_mutating(name) and not self.config.allow_mutating:
                raise PermissionError(
                    f"agent_loop: tool {name!r} changes platform state; set allow_mutating=True to allowlist it")
        tools = _tool_catalog(allow) if allow else []
        token = _mcp_token(self.config.mcp_connection_id) if allow else None

        user = f"Goal: {goal.strip()}"
        if context.strip():
            user += f"\n\nContext:\n{context.strip()[:6000]}"
        messages = [{"role": "system", "content": self._protocol(tools)}, {"role": "user", "content": user}]
        steps: list[dict[str, Any]] = []
        tools_called: list[str] = []
        final: str | None = None
        llm_calls = 0
        self._model_used = ""

        for i in range(int(self.config.max_steps)):
            content = self._chat(messages)
            llm_calls += 1
            decision = parse_decision(content)
            if decision is None:
                # The model answered in prose: that text is its answer.
                final = _THINK.sub("", content).strip()
                steps.append({"step": i, "action": "final", "note": "non-JSON reply taken as the answer"})
                break
            action = str(decision.get("action") or "").lower()
            if (action == "final" and tools and self.config.require_tool_call and not tools_called
                    and i < int(self.config.max_steps) - 1):
                steps.append({"step": i, "action": "rejected_final", "note": "no tool called yet"})
                messages.append({"role": "assistant", "content": json.dumps(decision)})
                messages.append({"role": "user", "content": (
                    "You must call one of the available tools before answering. "
                    'Reply {"action": "call_tool", "tool": "<name>", "arguments": {...}}.')})
                continue
            if action == "final" or not tools:
                final = str(decision.get("answer") or decision.get("final") or "").strip()
                if not final:
                    final = _THINK.sub("", content).strip()
                steps.append({"step": i, "action": "final"})
                break
            name = str(decision.get("tool") or "").strip()
            args = decision.get("arguments") if isinstance(decision.get("arguments"), dict) else {}
            if name not in allow:
                obs = {"ok": False, "error": f"tool {name!r} is not allowed; allowed: {allow}"}
            else:
                obs = _call_tool(name, args, token=token, timeout_s=float(self.config.timeout_s))
                tools_called.append(name)
            obs_text = json.dumps(obs, default=str)[:3000]
            steps.append({"step": i, "action": "call_tool", "tool": name, "arguments": args,
                          "ok": bool(obs.get("ok")), "observation": obs_text[:500]})
            messages.append({"role": "assistant", "content": json.dumps(decision)})
            messages.append({"role": "user", "content": f"Observation: {obs_text}\nNext JSON reply:"})

        if final is None:
            messages.append({"role": "user", "content": 'Step limit reached. Reply {"action": "final", "answer": "..."} now.'})
            content = self._chat(messages)
            llm_calls += 1
            decision = parse_decision(content) or {}
            final = str(decision.get("answer") or "").strip() or _THINK.sub("", content).strip()
            steps.append({"step": len(steps), "action": "final", "note": "forced after max_steps"})

        return {"output": AgentResult(
            final=final,
            steps=steps,
            mode="llm",
            metadata={
                "provider": str(self.config.provider),
                "model": self._model_used,
                "llm_called": True,
                "llm_calls": llm_calls,
                "tools_called": tools_called,
            },
        )}
