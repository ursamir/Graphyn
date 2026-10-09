"""McpToolCallNode — invoke a Graphyn MCP tool in-process by name.

Safety: the tool must be in ``tool_allowlist``; state-changing tools also need
``allow_mutating=True``. When the platform requires auth (production), the
call is authenticated with a token from a credential connection of kind
``graphyn_mcp`` (an operator or least-privilege *agent* token, see
``POST /api/v1/agents/{id}/tokens``). The token is resolved at run time and
never stored in the Graph IR; RBAC for user/agent tokens is enforced per tool.
"""
from __future__ import annotations

import importlib
import threading
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
        _types = importlib.import_module("mcp_tool_call.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

ToolCallResult = _types.ToolCallResult

log = logging.getLogger(__name__)

CREDENTIAL_KIND = "graphyn_mcp"


def _register_credential_kind() -> None:
    """Register the ``graphyn_mcp`` credential kind (idempotent)."""
    try:
        from app.core.credentials.kinds import CredentialKind, KindField, get_kind, register_kind
    except Exception:  # pragma: no cover — credentials module unavailable
        return
    if get_kind(CREDENTIAL_KIND) is not None:
        return
    register_kind(CredentialKind(
        id=CREDENTIAL_KIND,
        label="Graphyn MCP token",
        description=(
            "Token used by mcp_tool_call / agent_loop to call Graphyn MCP tools "
            "in-process (an agent principal token is recommended)."
        ),
        fields=[KindField(name="token", secret=True, required=True,
                          description="Graphyn API / agent token (shown once when minted).")],
    ))


_register_credential_kind()


def resolve_mcp_token(connection_id: str) -> str | None:
    """Return the MCP auth token for this call, or None when auth is not configured.

    Precedence: explicit ``connection_id`` > workspace default for kind
    ``graphyn_mcp``. Raises ``NeedsCredentialsError`` when the platform
    requires auth and no connection is available (fail closed).
    """
    from app.core.config import api_token, auth_required
    from app.core.trust.identity import token_auth_configured

    needs_token = bool(api_token() or token_auth_configured() or auth_required())
    if not needs_token:
        return None
    from app.core.credentials.resolve import NeedsCredentialsError, resolve_connection

    try:
        resolved = resolve_connection(kind=CREDENTIAL_KIND, connection_id=(connection_id or None), required=True)
    except NeedsCredentialsError as exc:
        raise NeedsCredentialsError(
            "mcp_tool_call: the platform requires auth for MCP tools — set "
            "config.connection_id to a credential of kind 'graphyn_mcp' (agent token) "
            f"or set a workspace default for that kind. ({exc})"
        ) from exc
    token = str((resolved.get("payload") or {}).get("token") or "")
    if not token:
        raise NeedsCredentialsError(
            f"mcp_tool_call: credential {resolved.get('connection_id')!r} (graphyn_mcp) has no token"
        )
    return token

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


# Tools that mutate platform state, execute code/pipelines, touch credentials,
# or reach the network. Refused unless ``allow_mutating=True`` (and allowlisted).
MUTATING_TOOLS: frozenset[str] = frozenset({
    "execute_pipeline", "pause_run", "resume_run", "cancel_run", "replay_run",
    "install_plugin", "uninstall_plugin", "manage_plugin",
    "create_credential", "get_credential", "update_credential", "revoke_credential",
    "propose_graph", "accept_proposal", "reject_proposal",
    "save_pipeline", "publish_pipeline", "promote_pipeline", "rollback_pipeline",
    "instantiate_template", "materialize_template",
    "register_model", "request_model_prod", "approve_model_prod",
    "upsert_schedule", "enable_schedule", "delete_schedule", "run_schedule_now",
    "put_webhooks", "test_webhook", "mark_notifications_read",
    "create_ship_package", "download_ship_package", "promote_ship_package",
    "export_audit", "upload_dataset_file", "optimize_execution",
})
MUTATING_PREFIXES: tuple[str, ...] = (
    "create_", "update_", "delete_", "remove_", "revoke_", "promote_", "approve_",
    "accept_", "reject_", "install_", "uninstall_", "manage_", "put_", "post_",
    "upsert_", "enable_", "disable_", "publish_", "rollback_", "cancel_", "pause_",
    "resume_", "replay_", "run_", "execute_", "register_", "request_", "save_",
    "upload_", "download_", "mark_", "materialize_", "instantiate_", "test_",
    "set_", "write_", "send_", "export_", "import_",
)


def is_mutating_tool(name: str) -> bool:
    return name in MUTATING_TOOLS or name.startswith(MUTATING_PREFIXES)


def _request_from_inputs(config, inputs) -> tuple[str, dict]:
    req = _dump(inputs.get("input"))
    name = ""
    args: Any = None
    if isinstance(req, dict):
        name = str(req.get("tool") or req.get("tool_name") or "")
        args = req.get("arguments")
    data_name = inputs.get("tool_name")
    if data_name is not None:
        name = str(_dump(data_name) or "")
    if inputs.get("arguments") is not None:
        args = _dump(inputs.get("arguments"))
    pinned = str(config.tool_name or "").strip()
    if pinned:
        if name and name != pinned:
            raise PermissionError(
                f"mcp_tool_call: input requested tool {name!r} but config.tool_name pins {pinned!r}"
            )
        name = pinned
    if args is None:
        args = {}
    if not isinstance(args, dict):
        args = {"value": args}
    return name.strip(), dict(args)


def _run_with_timeout(fn, timeout_s: float):
    if timeout_s <= 0:
        return fn()
    box: dict[str, Any] = {}

    def _target():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — re-raised in caller thread
            box["error"] = exc

    t = threading.Thread(target=_target, name="mcp_tool_call", daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise TimeoutError(f"mcp_tool_call: tool exceeded timeout_s={timeout_s}")
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _mcp_tool(config, inputs, types):
    if str(config.server or "graphyn") != "graphyn":
        raise ValueError(f"mcp_tool_call: only server='graphyn' is supported (got {config.server!r})")
    name, args = _request_from_inputs(config, inputs)
    if not name:
        raise ValueError("mcp_tool_call: tool name is required (config.tool_name, tool_name port, or input.tool)")
    allowlist = [str(t) for t in (config.tool_allowlist or [])]
    if not allowlist:
        raise PermissionError(
            "mcp_tool_call: config.tool_allowlist is empty — refusing to call any tool. "
            f"Add {name!r} to tool_allowlist to permit it."
        )
    if name not in allowlist:
        raise PermissionError(f"mcp_tool_call: tool {name!r} is not in tool_allowlist {allowlist}")
    if is_mutating_tool(name) and not bool(config.allow_mutating):
        raise PermissionError(
            f"mcp_tool_call: tool {name!r} mutates platform state / touches secrets; "
            "set allow_mutating=True to permit it"
        )

    from app.mcp.auth import check_auth
    from app.mcp.server import get_tool

    token = resolve_mcp_token(str(getattr(config, "connection_id", "") or ""))
    if token:
        meta = dict(args.get("_meta") or {}) if isinstance(args.get("_meta"), dict) else {}
        meta["auth_token"] = token
        args = {**args, "_meta": meta}
    auth_error = check_auth(args, tool_name=name)
    if auth_error is not None:
        raise PermissionError(f"mcp_tool_call: {auth_error.get('message') or 'unauthorized'}")
    tool = get_tool(name)
    if tool is None:
        raise ValueError(f"mcp_tool_call: unknown tool {name!r}")

    handler = tool["handler"]
    try:
        result = _run_with_timeout(lambda: handler(args), float(config.timeout_s))
    except TimeoutError as exc:
        return _T(types, "ToolCallResult", tool=name, ok=False, result=None, error=str(exc))
    except Exception as exc:  # handler failure → structured result, like the MCP server
        return _T(types, "ToolCallResult", tool=name, ok=False, result=None,
                  error=f"{type(exc).__name__}: {exc}")
    if isinstance(result, dict) and result.get("error") is True:
        return _T(types, "ToolCallResult", tool=name, ok=False, result=result,
                  error=str(result.get("message") or result.get("error_type") or "tool error"))
    return _T(types, "ToolCallResult", tool=name, ok=True, result=result, error=None)



class McpToolCallNode(Node):
    """Invoke Graphyn MCP tool by name"""

    node_type: ClassVar[str] = "mcp_tool_call"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="mcp_tool_call",
        label="Mcp Tool Call",
        description="Invoke Graphyn MCP tool by name",
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
        "input": InputPort(name="input", data_type=object | None, required=False, description="ToolCallRequest (tool + arguments), e.g. from tool_router"),
        "tool_name": InputPort(name="tool_name", data_type=object | None, required=False, description="str (must be in tool_allowlist)"),
        "arguments": InputPort(name="arguments", data_type=object | None, required=False, description="dict"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ToolCallResult NEW"),
    }

    class Config(NodeConfig):
        timeout_s: float = Field(default=60.0, ge=0, title="Timeout s", description="Per-call timeout in seconds (0 = no limit).")
        server: str = Field(default='graphyn', title="Server", description="MCP server (only 'graphyn' in-process).")
        tool_name: str = Field(default="", title="Tool name", description="Pin the tool; data may not request a different one.")
        tool_allowlist: list = Field(default_factory=list, title="Tool allowlist", description="Tools this node may call. Empty → refuse all.")
        allow_mutating: bool = Field(default=False, title="Allow mutating", description="Permit state-changing / credential / execution tools (still must be allowlisted).")
        connection_id: str = Field(default="", title="Credential connection id", description="Credential of kind graphyn_mcp (agent/API token) used when the platform requires auth. Empty → workspace default for that kind.")

    def process(self, inputs=None, **kwargs):
        """Run the node."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"mcp_tool_call: required dependency missing ({exc}). Install the plugin dependencies.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _mcp_tool(self.config, inputs, _types)}
