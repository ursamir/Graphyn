#!/usr/bin/env python3
"""Graphyn MCP agentic self-test — stdio client against live graphyn-api container.

Invokes real MCP tools via the official MCP Python SDK over stdio.
Auth token read from env GRAPHYN_API_TOKEN (never printed).
Transcript written to docs/_gen/MCP_AGENTIC_SELFTEST.md (secrets redacted).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Prefer running inside container where `mcp` + app are installed.
os.environ.setdefault("GRAPHYN_SKIP_PLUGIN_LOAD", "0")

TRANSCRIPT: list[dict[str, Any]] = []


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if any(s in lk for s in ("token", "password", "secret", "api_key", "authorization")):
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    if isinstance(obj, str) and len(obj) > 2000:
        return obj[:2000] + f"...<truncated {len(obj)} chars>"
    return obj


def record(tool: str, args: dict[str, Any], outcome: Any, ok: bool, err: str | None = None) -> None:
    safe_args = _redact({k: v for k, v in args.items() if k != "_meta"})
    if "_meta" in args:
        safe_args["_meta"] = {"auth_token": "***REDACTED***"} if args.get("_meta", {}).get("auth_token") else {}
    TRANSCRIPT.append(
        {
            "ts": _now(),
            "tool": tool,
            "args": safe_args,
            "ok": ok,
            "error": err,
            "outcome": _redact(outcome),
        }
    )


def _meta() -> dict[str, Any]:
    tok = (os.environ.get("GRAPHYN_API_TOKEN") or "").strip()
    if not tok:
        raise SystemExit("GRAPHYN_API_TOKEN required")
    return {"_meta": {"auth_token": tok}}


async def call_tool(session, name: str, arguments: dict[str, Any]) -> Any:
    args = {**arguments, **_meta()}
    try:
        result = await session.call_tool(name, arguments=args)
        # result.content is list of TextContent
        texts = []
        for c in (result.content or []):
            t = getattr(c, "text", None)
            if t is not None:
                texts.append(t)
            else:
                texts.append(str(c))
        raw = texts[0] if len(texts) == 1 else texts
        parsed: Any = raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
        # Treat structured error dicts as failure for honesty
        ok = True
        err = None
        if isinstance(parsed, dict) and (parsed.get("error") or parsed.get("error_type") == "unauthorized"):
            ok = False
            err = parsed.get("error_type") or parsed.get("message") or "error"
        record(name, args, parsed, ok, err)
        return parsed
    except Exception as exc:
        record(name, args, None, False, f"{type(exc).__name__}: {exc}")
        raise


async def run() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # Launch MCP server as subprocess (same env / GRAPHYN_HOME as API if run via docker exec)
    child_env = dict(os.environ)
    # Lean MCP child: never mass-install PluginPackage into a fresh home.
    child_env.setdefault("GRAPHYN_AUTO_INSTALL_PLUGINS", "0")
    child_env.setdefault("GRAPHYN_ISOLATED_BOOT_HEAVY", "0")
    child_env.setdefault("GRAPHYN_SMTP_DRY_RUN", "1")
    child_env.pop("GRAPHYN_PLUGINS_DIR", None)
    child_env["GRAPHYN_ENV"] = child_env.get("GRAPHYN_ENV") or "development"
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp.server"],
        env=child_env,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = sorted(t.name for t in tools.tools)
            record("list_tools", {}, {"count": len(tool_names), "names": tool_names}, True)

            # 1) Discovery
            packs = await call_tool(session, "list_packs", {})
            await call_tool(session, "describe_pack", {"pack": "Common"})
            await call_tool(session, "search_templates", {"pack": "Agents", "limit": 5})
            await call_tool(session, "search_templates", {"q": "email-alert", "limit": 5})
            await call_tool(session, "get_node_spec", {"node_type": "llm_chat"})
            await call_tool(session, "get_node_spec", {"node_type": "send_email"})
            await call_tool(session, "list_plugins", {})

            # 2) Create/register a NEW small plugin via install_plugin
            plugin_src = os.environ.get(
                "GRAPHYN_SELFTEST_PLUGIN_SRC",
                "/app/plugins/_agent_selftest_echo",
            )
            install_res = await call_tool(
                session,
                "install_plugin",
                {"source": plugin_src},
            )
            await call_tool(session, "manage_plugin", {"name": "agent-selftest-echo", "action": "enable"})
            await call_tool(session, "list_plugins", {})

            # 3) Materialize / build 3 distinct usecase graphs
            graphs: dict[str, Any] = {}

            # Will fill llm_notify / rag / common / echo below

            # Usecase A: LLM stub + notify path (llm_chat stub → send_email dry)
            g_llm = await call_tool(
                session,
                "generate_graph",
                {
                    "name": "mcp-selftest-llm-notify",
                    "description": "LLM stub then send_email dry-run notify",
                    "nodes": [
                        {
                            "id": "chat",
                            "node_type": "llm_chat",
                            "config": {
                                "stub": True,
                                "provider": "stub",
                                "model": "stub-model",
                                "system_prompt": "Say hello from MCP selftest",
                            },
                        },
                        {
                            "id": "mail",
                            "node_type": "send_email",
                            "config": {
                                "to": "selftest@example.com",
                                "subject": "MCP selftest llm-notify",
                                "body_template": "LLM notify from MCP selftest",
                                "dry_run": True,
                            },
                        },
                    ],
                    "edges": [
                        {
                            "src_id": "chat",
                            "src_port": "output",
                            "dst_id": "mail",
                            "dst_port": "input",
                        }
                    ],
                },
            )
            graphs["llm_notify"] = g_llm

            # Usecase B: RAG stub path — materialize marketplace template if possible
            mat = await call_tool(
                session,
                "materialize_template",
                {"template_id": "tpl-rag-query-faiss-support"},
            )
            if isinstance(mat, dict) and mat.get("error"):
                # fallback search + first materializable
                search = await call_tool(
                    session,
                    "search_templates",
                    {"pack": "RAG", "q": "query", "limit": 3},
                )
                tid = None
                if isinstance(search, dict):
                    tpls = search.get("templates") or search.get("results") or []
                    if tpls:
                        tid = tpls[0].get("id") or tpls[0].get("template_id")
                if tid:
                    mat = await call_tool(session, "materialize_template", {"template_id": tid})
            graphs["rag"] = mat

            # Usecase C: simple Common pipeline (python_code / set_map / json_transform)
            g_common = await call_tool(
                session,
                "generate_graph",
                {
                    "name": "mcp-selftest-common-pipeline",
                    "description": "set_map → python_code → json_transform",
                    "nodes": [
                        {
                            "id": "map1",
                            "node_type": "set_map",
                            "config": {"set": {"hello": "world", "n": 1}},
                        },
                        {
                            "id": "py1",
                            "node_type": "python_code",
                            "config": {
                                "source": "output = {'payload': dict((inputs.get('input') or {}) if isinstance(inputs, dict) else {}), 'ok': True}"
                            },
                        },
                        {
                            "id": "jt1",
                            "node_type": "json_transform",
                            "config": {"path": "$"},
                        },
                    ],
                    # auto-chain if edges omitted; explicit ports for honesty
                    "edges": [
                        {"src_id": "map1", "src_port": "output", "dst_id": "py1", "dst_port": "input"},
                        {"src_id": "py1", "src_port": "output", "dst_id": "jt1", "dst_port": "input"},
                    ],
                },
            )
            graphs["common"] = g_common

            g_echo = await call_tool(
                session,
                "generate_graph",
                {
                    "name": "mcp-selftest-echo-plugin",
                    "description": "Newly registered agent_selftest_echo plugin",
                    "nodes": [
                        {
                            "id": "echo1",
                            "node_type": "agent_selftest_echo",
                            "config": {"message": "mcp-e2e"},
                        }
                    ],
                },
            )
            graphs["echo_plugin"] = g_echo

            # Also try email-alert / notify-on-run / llm-local-chat marketplace
            for tid in (
                "tpl-agents-email-alert-support",
                "tpl-agents-notify-on-run-mlops",
                "tpl-agents-llm-local-chat-support",
            ):
                await call_tool(session, "materialize_template", {"template_id": tid})

            project = os.environ.get("GRAPHYN_SELFTEST_PROJECT", "mcp-agentic-selftest")
            await call_tool(session, "list_projects", {})

            run_ids: list[str] = []
            # Execute lean usecases first; RAG may need RAG pack nodes not in lean home.
            exec_keys = ["llm_notify", "common", "echo_plugin", "rag"]
            for key in exec_keys:
                g = graphs.get(key)
                if g is None:
                    continue
                graph_ir = None
                if isinstance(g, dict):
                    if "graph" in g:
                        graph_ir = g["graph"]
                    elif g.get("ir_version") or g.get("schema_version") or g.get("nodes"):
                        graph_ir = g
                    elif g.get("error"):
                        continue
                if not graph_ir:
                    continue

                v = await call_tool(session, "validate_graph", {"graph": graph_ir})
                pipe_name = f"uc-{key}"
                await call_tool(
                    session,
                    "save_pipeline",
                    {"project": project, "pipeline": pipe_name, "graph": graph_ir},
                )
                exe = await call_tool(
                    session,
                    "execute_pipeline",
                    {"graph": graph_ir, "use_cache": False},
                )
                if isinstance(exe, dict) and exe.get("run_id"):
                    run_ids.append(exe["run_id"])

            # Poll runs
            for rid in run_ids:
                for _ in range(30):
                    st = await call_tool(
                        session,
                        "inspect_run",
                        {"run_id": rid, "status_only": True},
                    )
                    status = (st or {}).get("status") if isinstance(st, dict) else None
                    if status in ("succeeded", "failed", "cancelled", "error", "completed"):
                        break
                    await asyncio.sleep(1.0)
                await call_tool(session, "inspect_run", {"run_id": rid})
                await call_tool(session, "list_artifacts", {"run_id": rid})
                await call_tool(session, "get_run_outputs", {"run_id": rid})

            await call_tool(session, "list_notifications", {"limit": 20})
            await call_tool(session, "list_runs", {"limit": 10})

    return 0


def write_report(path: Path) -> None:
    ok_n = sum(1 for t in TRANSCRIPT if t.get("ok"))
    fail_n = sum(1 for t in TRANSCRIPT if not t.get("ok"))
    lines = [
        "# MCP Agentic Self-Test Transcript",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| **Date** | {_now()} |",
        f"| **Branch tip** | `{os.environ.get('GRAPHYN_TIP', 'unknown')}` |",
        f"| **Transport** | MCP stdio → `python -m app.mcp.server` (inside graphyn-api / host) |",
        f"| **Auth** | Bearer from GRAPHYN_API_TOKEN (redacted) |",
        f"| **Calls** | {len(TRANSCRIPT)} ({ok_n} ok / {fail_n} fail) |",
        "",
        "## Tool call transcript",
        "",
    ]
    for i, t in enumerate(TRANSCRIPT, 1):
        lines.append(f"### {i}. `{t['tool']}` — {'OK' if t['ok'] else 'FAIL'}")
        lines.append("")
        lines.append(f"- **ts:** {t['ts']}")
        if t.get("error"):
            lines.append(f"- **error:** `{t['error']}`")
        lines.append("- **args:**")
        lines.append("```json")
        lines.append(json.dumps(t["args"], indent=2, default=str))
        lines.append("```")
        lines.append("- **outcome:**")
        lines.append("```json")
        lines.append(json.dumps(t["outcome"], indent=2, default=str)[:8000])
        lines.append("```")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    # also dump raw json
    path.with_suffix(".json").write_text(
        json.dumps(TRANSCRIPT, indent=2, default=str), encoding="utf-8"
    )


def main() -> int:
    try:
        rc = asyncio.run(run())
    except Exception:
        traceback.print_exc()
        record("_fatal", {}, None, False, traceback.format_exc()[-500:])
        rc = 1
    out = Path(os.environ.get("GRAPHYN_SELFTEST_OUT", "/tmp/MCP_AGENTIC_SELFTEST.md"))
    write_report(out)
    print(f"Wrote {out} calls={len(TRANSCRIPT)}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
