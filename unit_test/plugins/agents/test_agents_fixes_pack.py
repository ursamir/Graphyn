"""Regression tests for Agents pack defect fixes (hitl, guardrail, mcp, router,
schema validate, prompt template, memory store, agent loop, llm_chat)."""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO = Path(__file__).resolve().parents[3]
AGENTS = REPO / "PluginPackage" / "Agents"
_REAL_THREAD_START = threading.Thread.start  # captured before conftest's autouse patch


@pytest.fixture(autouse=True)
def _real_threads(patch_threads, monkeypatch):
    """These nodes rely on real threads (timeouts, locking); undo the no-op patch."""
    monkeypatch.setattr(threading.Thread, "start", _REAL_THREAD_START)


def _load(plugin: str):
    """Import PluginPackage/Agents/<plugin> as a uniquely named package."""
    name = f"_agents_fix_{plugin}"
    if not (AGENTS / plugin).is_dir():
        pytest.skip(f"Agents/{plugin} is not in the current PluginPackage scope")
    if name in sys.modules:
        return sys.modules[f"{name}.nodes"]
    root = AGENTS / plugin
    spec = importlib.util.spec_from_file_location(
        name, root / "__init__.py", submodule_search_locations=[str(root)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return sys.modules[f"{name}.nodes"]


def _toml(plugin: str) -> dict:
    import tomllib

    return tomllib.loads((AGENTS / plugin / "plugin.toml").read_text())


def _assert_schema_sync(plugin: str, node_cls) -> None:
    schema = _toml(plugin)["config_schema"][node_cls.node_type]
    fields = node_cls.Config.model_fields
    assert set(schema) == set(fields), (plugin, set(schema) ^ set(fields))
    for key, spec in schema.items():
        f = fields[key]
        default = f.default_factory() if f.default_factory is not None else f.default
        assert spec["default"] == default, (plugin, key, spec["default"], default)
        js = node_cls.Config.model_json_schema()["properties"][key]
        if "enum" in js:
            assert spec.get("enum") == js["enum"], (plugin, key)


@pytest.mark.parametrize(
    "plugin",
    [
        "hitl_approve", "guardrail_filter", "mcp_tool_call", "tool_router",
        "output_schema_validate", "prompt_template", "memory_store", "agent_loop", "llm_chat",
    ],
)
def test_plugin_toml_matches_config(plugin):
    mod = _load(plugin)
    node_cls = next(
        v for v in vars(mod).values()
        if isinstance(v, type) and getattr(v, "node_type", None) == plugin and hasattr(v, "Config")
    )
    _assert_schema_sync(plugin, node_cls)


def _all_ports(node, out):
    assert set(out) == set(type(node).output_ports), (set(out), set(type(node).output_ports))


def _only_ports(out, *ports):
    """Branch-style nodes emit ONLY the active port(s); inactive keys are omitted."""
    assert set(out) == set(ports), (set(out), set(ports))


# ── 1. hitl_approve ───────────────────────────────────────────────────────────

@pytest.fixture
def hitl():
    return _load("hitl_approve")


@pytest.fixture
def hitl_ws(tmp_path, monkeypatch):
    """Project jail for hitl decision_dir (must resolve under project_dir)."""
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    return tmp_path


def _hitl_node(hitl, hitl_ws, **cfg):
    base = {"decision_dir": str(hitl_ws), "timeout_s": 0, "poll_interval_s": 0.01}
    base.update(cfg)
    node = hitl.HitlApproveNode(config=base)
    node._run_id = "run-1"
    return node


def test_hitl_payload_cannot_self_approve(hitl, hitl_ws):
    node = _hitl_node(hitl, hitl_ws)
    out = node.process({"input": {"approved": True, "action": "rm -rf"}})
    # Safety: a rejected gate must NOT emit the `approved` key at all — even
    # `approved: None` counts as produced and would run the approved branch.
    _only_ports(out, "rejected")
    assert out["rejected"]["approved"] is False
    assert "timeout" in out["rejected"]["reason"]
    assert out["rejected"]["payload"] == {"approved": True, "action": "rm -rf"}


def test_hitl_unattended_default_false_and_explicit_pass(hitl, hitl_ws):
    assert hitl.HitlApproveNode.Config().unattended_approve is False
    node = _hitl_node(hitl, hitl_ws, unattended_approve=True)
    out = node.process({"input": {"x": 1}})
    assert out == {"approved": {"x": 1}}
    assert list(hitl_ws.glob("*.unattended.json"))


def _decide_async(hitl, hitl_ws, decision_fn, run_id="run-1", gate="hitl_approve"):
    req_path, dec_path = hitl.decision_paths(hitl_ws, run_id, gate)

    def _worker():
        for _ in range(500):
            if req_path.is_file():
                req = json.loads(req_path.read_text())
                dec_path.write_text(json.dumps(decision_fn(req)))
                return
            time.sleep(0.01)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


def test_hitl_out_of_band_approval(hitl, hitl_ws):
    node = _hitl_node(hitl, hitl_ws, timeout_s=5, approver_roles=["release"])
    t = _decide_async(hitl, hitl_ws, lambda r: {
        "request_id": r["request_id"], "approved": True,
        "approver": "alice", "role": "release", "reason": "LGTM"})
    out = node.process({"input": {"model": "m1"}})
    t.join(1)
    assert out == {"approved": {"model": "m1"}}
    req_path, _ = hitl.decision_paths(hitl_ws, "run-1", "hitl_approve")
    rec = json.loads(req_path.read_text())
    assert rec["status"] == "approved" and rec["outcome"]["approver"] == "alice"


@pytest.mark.parametrize(
    "decision,why",
    [
        ({"approved": True, "approver": "bob", "role": "intern", "reason": "ok"}, "role"),
        ({"approved": True, "approver": "bob", "role": "release", "reason": ""}, "reason"),
        ({"approved": False, "approver": "bob", "role": "release", "reason": "no"}, "no"),
    ],
)
def test_hitl_invalid_or_denied_decision_rejects(hitl, hitl_ws, decision, why):
    node = _hitl_node(hitl, hitl_ws, timeout_s=5, approver_roles=["release"])
    t = _decide_async(hitl, hitl_ws, lambda r: {"request_id": r["request_id"], **decision})
    out = node.process({"input": 1})
    t.join(1)
    _only_ports(out, "rejected")
    assert why in out["rejected"]["reason"]


def test_hitl_stale_decision_ignored(hitl, hitl_ws):
    _, dec_path = hitl.decision_paths(hitl_ws, "run-1", "hitl_approve")
    dec_path.parent.mkdir(parents=True, exist_ok=True)
    dec_path.write_text(json.dumps({"request_id": "old", "approved": True,
                                    "approver": "x", "reason": "stale"}))
    out = _hitl_node(hitl, hitl_ws, timeout_s=0.1).process({"input": 1})
    _only_ports(out, "rejected")
    assert out["rejected"] is not None


def test_hitl_stub_fails_closed(hitl, hitl_ws):
    out = _hitl_node(hitl, hitl_ws, stub=True).process({"input": 1})
    assert out == {}


def test_hitl_decision_dir_escape_refused(hitl, hitl_ws, tmp_path):
    outside = tmp_path.parent / "outside_hitl_decisions"
    with pytest.raises(ValueError, match="project workspace"):
        hitl.decision_paths(str(outside), "run-1", "g")
    with pytest.raises(ValueError, match=r"\.\."):
        hitl.decision_paths("workspace/../etc", "run-1", "g")


# ── 2. guardrail_filter ───────────────────────────────────────────────────────

@pytest.fixture
def guard():
    return _load("guardrail_filter")


def test_guardrail_default_policies_block_secrets_and_email(guard):
    node = guard.GuardrailFilterNode()
    assert node.config.policies == ["pii", "secret"]
    with pytest.raises(RuntimeError, match="secret"):
        node.process({"input": "key sk-ABCDEFGHIJKLMNOP1234"})
    with pytest.raises(RuntimeError, match="pii"):
        node.process({"input": {"text": "hi", "meta": {"to": "a@b.com"}}})


def test_guardrail_empty_policies_fallback(guard):
    node = guard.GuardrailFilterNode(config={"policies": [], "action": "flag"})
    out = node.process({"input": "mail a@b.com"})
    _only_ports(out, "output", "violations")
    assert [h.rule for h in out["violations"]] == ["pii"]
    assert out["output"] == "mail a@b.com"


def test_guardrail_scans_all_strings_and_redacts_structure(guard):
    node = guard.GuardrailFilterNode(config={"action": "redact"})
    payload = {"text": "hello", "items": [{"note": "SK-abcdefghijklmnop"}, "x@y.org"], "n": 3}
    out = node.process({"input": payload})
    assert out["output"] == {"text": "hello", "items": [{"note": "[redacted]"}, "[redacted]"], "n": 3}
    assert sorted(h.rule for h in out["violations"]) == ["pii", "secret"]


def test_guardrail_redacts_only_active_rules(guard):
    node = guard.GuardrailFilterNode(config={"action": "redact", "policies": ["secret"]})
    out = node.process({"input": "sk-abcdefghijklmnop and a@b.com"})
    assert out["output"] == "[redacted] and a@b.com"


def test_guardrail_clean_input_emits_empty_violations(guard):
    out = guard.GuardrailFilterNode().process({"input": "all good"})
    # Clean input: `violations` branch is omitted (not an empty list).
    assert out == {"output": "all good"}


def test_guardrail_unknown_action_fails_closed(guard):
    with pytest.raises(ValidationError):
        guard.GuardrailFilterNode(config={"action": "allow"})
    cfg = guard.GuardrailFilterNode.Config.model_construct(policies=["pii"], action="allow", stub=False)
    with pytest.raises(RuntimeError, match="blocked"):
        guard._guardrail(cfg, {"input": "a@b.com"}, guard._types)


# ── 3. mcp_tool_call ──────────────────────────────────────────────────────────

@pytest.fixture
def mcp():
    return _load("mcp_tool_call")


@pytest.fixture
def fake_tools(monkeypatch):
    import app.mcp.server as server

    calls = []
    tools = {
        "list_nodes": {"handler": lambda a: calls.append(("list_nodes", a)) or {"nodes": ["x"]}},
        "install_plugin": {"handler": lambda a: calls.append(("install_plugin", a)) or {"ok": True}},
        "slow": {"handler": lambda a: time.sleep(2) or {"ok": True}},
        "boom": {"handler": lambda a: (_ for _ in ()).throw(RuntimeError("kaput"))},
    }
    monkeypatch.setattr(server, "get_tool", lambda name: tools.get(name))
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    return calls


def test_mcp_empty_allowlist_refuses(mcp, fake_tools):
    with pytest.raises(PermissionError, match="tool_allowlist is empty"):
        mcp.McpToolCallNode().process({"tool_name": "list_nodes", "arguments": {}})
    assert fake_tools == []


def test_mcp_not_in_allowlist_refused(mcp, fake_tools):
    node = mcp.McpToolCallNode(config={"tool_allowlist": ["list_nodes"]})
    with pytest.raises(PermissionError, match="not in tool_allowlist"):
        node.process({"tool_name": "get_run", "arguments": {}})


def test_mcp_allowlisted_call_and_router_request(mcp, fake_tools):
    node = mcp.McpToolCallNode(config={"tool_allowlist": ["list_nodes"]})
    out = node.process({"input": {"tool": "list_nodes", "arguments": {"q": 1}}})["output"]
    assert out.ok and out.result == {"nodes": ["x"]} and out.tool == "list_nodes"
    assert fake_tools == [("list_nodes", {"q": 1})]


def test_mcp_mutating_denied_unless_allowed(mcp, fake_tools):
    cfg = {"tool_allowlist": ["install_plugin"]}
    with pytest.raises(PermissionError, match="allow_mutating"):
        mcp.McpToolCallNode(config=cfg).process({"tool_name": "install_plugin", "arguments": {}})
    assert fake_tools == []
    out = mcp.McpToolCallNode(config={**cfg, "allow_mutating": True}).process(
        {"tool_name": "install_plugin", "arguments": {}})["output"]
    assert out.ok
    for name in ("delete_schedule", "promote_pipeline", "cancel_run", "put_webhooks",
                 "create_credential", "execute_pipeline", "uninstall_plugin"):
        assert mcp.is_mutating_tool(name), name
    assert not mcp.is_mutating_tool("list_nodes")


def test_mcp_pinned_tool_name_blocks_data_override(mcp, fake_tools):
    node = mcp.McpToolCallNode(config={"tool_allowlist": ["list_nodes", "get_run"], "tool_name": "list_nodes"})
    with pytest.raises(PermissionError, match="pins"):
        node.process({"tool_name": "get_run"})
    assert node.process({})["output"].ok


def test_mcp_timeout_enforced(mcp, fake_tools):
    node = mcp.McpToolCallNode(config={"tool_allowlist": ["slow"], "timeout_s": 0.1})
    t0 = time.monotonic()
    out = node.process({"tool_name": "slow"})["output"]
    assert time.monotonic() - t0 < 1.5
    assert out.ok is False and "timeout" in out.error


def test_mcp_handler_error_structured(mcp, fake_tools):
    out = mcp.McpToolCallNode(config={"tool_allowlist": ["boom"]}).process({"tool_name": "boom"})["output"]
    assert out.ok is False and "kaput" in out.error


def test_mcp_auth_enforced(mcp, fake_tools, monkeypatch):
    """With platform auth on, the node resolves a graphyn_mcp credential and
    injects its token; without one it fails closed; data cannot spoof it."""
    import app.core.credentials.resolve as resolve

    monkeypatch.setenv("GRAPHYN_API_TOKEN", "s3cret")
    node = mcp.McpToolCallNode(config={"tool_allowlist": ["list_nodes"]})
    with pytest.raises(resolve.NeedsCredentialsError, match="graphyn_mcp"):
        node.process({"tool_name": "list_nodes", "arguments": {}})
    assert fake_tools == []

    stored = {"token": "wrong"}
    monkeypatch.setattr(resolve, "resolve_connection", lambda **kw: {
        "connection_id": "c1", "kind": kw["kind"], "source": "store", "payload": dict(stored)})
    with pytest.raises(PermissionError, match="Authentication"):
        node.process({"tool_name": "list_nodes", "arguments": {"_meta": {"auth_token": "s3cret"}}})
    assert fake_tools == []

    stored["token"] = "s3cret"
    out = node.process({"tool_name": "list_nodes", "arguments": {}})
    assert out["output"].ok and [c[0] for c in fake_tools] == ["list_nodes"]
    assert fake_tools[0][1]["_meta"]["auth_token"] == "s3cret"  # same shape the MCP server passes


def test_mcp_credential_kind_registered(mcp):
    from app.core.credentials.kinds import get_kind

    kind = get_kind("graphyn_mcp")
    assert kind is not None and any(f.name == "token" and f.secret for f in kind.fields)


# ── 4. tool_router ────────────────────────────────────────────────────────────

@pytest.fixture
def router():
    return _load("tool_router")


def test_router_honors_explicit_tool_and_arguments(router):
    node = router.ToolRouterNode(config={"tools": ["search", "delete"]})
    req = router.ToolCallRequest(tool="search", arguments={"q": "cats", "k": 3})
    out = node.process({"input": req})
    _all_ports(node, out)
    assert isinstance(out["output"], router.ToolCallRequest)
    assert out["output"].tool == "search" and out["output"].arguments == {"q": "cats", "k": 3}
    assert out["unmatched"] is None


def test_router_unknown_explicit_tool_unmatched(router):
    node = router.ToolRouterNode(config={"tools": ["search"]})
    out = node.process({"input": {"tool": "rm", "arguments": {"p": "/"}}})
    assert out["output"] is None
    assert out["unmatched"].tool == "rm" and out["unmatched"].arguments == {"p": "/"}


def test_router_negation_and_most_specific(router):
    node = router.ToolRouterNode(config={"tools": ["delete", "research"]})
    out = node.process({"input": "please do not delete; do research"})
    assert out["output"].tool == "research"
    node2 = router.ToolRouterNode(config={"tools": ["search", {"name": "web_search", "keywords": ["web search"]}]})
    assert node2.process({"input": "run a web search for cats"})["output"].tool == "web_search"


def test_router_word_boundary(router):
    node = router.ToolRouterNode(config={"tools": ["cat"]})
    out = node.process({"input": "concatenate strings"})
    assert out["output"] is None and out["unmatched"] is not None


def test_router_unmatched_instead_of_raise_and_fallback(router):
    strict = router.ToolRouterNode(config={"tools": ["search"]})
    out = strict.process({"input": "hello"})
    assert out["output"] is None and out["unmatched"].arguments == {"input": "hello"}
    loose = router.ToolRouterNode(config={"tools": ["echo"], "strict": False})
    assert loose.process({"input": "hello"})["output"].tool == "echo"


# ── 5. output_schema_validate ─────────────────────────────────────────────────

@pytest.fixture
def osv():
    return _load("output_schema_validate")


SCHEMA = {
    "type": "object",
    "required": ["name", "age"],
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string", "enum": ["a", "b"]}},
        "addr": {"type": "object", "required": ["city"], "properties": {"city": {"type": "string"}}},
        "nick": {"type": ["string", "null"]},
    },
}


def _osv(osv, **cfg):
    return osv.OutputSchemaValidateNode(config={"json_schema": SCHEMA, "strict": False, **cfg})


def test_osv_parses_json_string_and_chat_message(osv):
    chat = _load("llm_chat").ChatMessage
    node = _osv(osv)
    good = {"name": "x", "age": 3, "tags": ["a"], "nick": None}
    out = node.process({"input": json.dumps(good)})
    assert out == {"output": good}
    out = node.process({"input": chat(role="assistant", content="```json\n" + json.dumps(good) + "\n```")})
    assert out["output"] == good
    bad = node.process({"input": chat(role="assistant", content='{"name": 1}')})
    _only_ports(bad, "errors")
    assert bad["errors"]


def test_osv_invalid_json_string(osv):
    out = _osv(osv).process({"input": "not json"})
    _only_ports(out, "errors")
    assert "invalid JSON" in out["errors"][0]


def test_osv_bool_not_integer_nested_enum_items(osv):
    node = _osv(osv)
    errs = node.process({"input": {"name": "x", "age": True}})["errors"]
    assert any("$.age" in e for e in errs)
    errs = node.process({"input": {"name": "x", "age": 1, "tags": ["a", "z", 3]}})["errors"]
    assert any("$.tags[1]" in e and "enum" in e for e in errs)
    assert any("$.tags[2]" in e for e in errs)
    errs = node.process({"input": {"name": "x", "age": 1, "addr": {}}})["errors"]
    assert any("city" in e for e in errs)
    errs = node.process({"input": {"name": "x", "age": 1, "nick": 5}})["errors"]
    assert any("$.nick" in e for e in errs)


def test_osv_strict_raises(osv):
    with pytest.raises(ValueError, match="missing required"):
        _osv(osv, strict=True).process({"input": "{}"})


# ── 6. prompt_template ────────────────────────────────────────────────────────

@pytest.fixture
def pt():
    return _load("prompt_template")


def test_prompt_format_engine(pt):
    node = pt.PromptTemplateNode(config={"template": "Hi {name}, {n}", "engine": "format"})
    assert node.process({"variables": {"name": "Ann", "n": 2}})["output"] == "Hi Ann, 2"
    with pytest.raises(ValueError, match="missing variable 'name'"):
        node.process({"variables": {"n": 1}})
    evil = pt.PromptTemplateNode(config={"template": "{x.__class__}"})
    with pytest.raises(ValueError, match="private"):
        evil.process({"variables": {"x": 1}})


def test_prompt_jinja_engine(pt):
    node = pt.PromptTemplateNode(config={"template": "Hello {{ name }}!", "engine": "jinja"})
    assert node.process({"variables": {"name": "Bob"}})["output"] == "Hello Bob!"
    with pytest.raises(ValueError, match="undefined"):
        node.process({"variables": {}})


def test_prompt_jinja_fallback_without_jinja2(pt, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("jinja2"):
            raise ImportError("no jinja2")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert pt._render_jinja("x={{ a.b }}", {"a": {"b": 5}}) == "x=5"
    with pytest.raises(ValueError, match="undefined"):
        pt._render_jinja("{{ missing }}", {})


def test_prompt_unknown_engine_rejected(pt):
    with pytest.raises(ValidationError):
        pt.PromptTemplateNode(config={"engine": "mako"})


# ── 7. memory_store ───────────────────────────────────────────────────────────

@pytest.fixture
def mem():
    return _load("memory_store")


def test_memory_write_without_op_is_set(mem, tmp_path):
    node = mem.MemoryStoreNode(config={"persist_path": str(tmp_path / "m.json")})
    node.process({"input": {"key": "k", "value": 42}})
    assert node.process({"input": {"key": "k"}})["output"].value == 42
    node.process({"input": mem.MemoryOp(key="k2", value="v")})
    assert node.process({"input": "k2"})["output"].value == "v"
    node.process({"input": {"op": "delete", "key": "k"}})
    assert node.process({"input": {"key": "k"}})["output"].value is None
    with pytest.raises(ValueError, match="unknown op"):
        node.process({"input": {"op": "drop", "key": "k"}})


def test_memory_persist_path_directory(mem, tmp_path):
    node = mem.MemoryStoreNode(config={"persist_path": str(tmp_path / "memdir"), "namespace": "ns"})
    node.process({"input": {"key": "a", "value": 1}})
    stored = json.loads((tmp_path / "memdir" / "memory.json").read_text())
    assert stored == {"ns": {"a": 1}}
    assert not list((tmp_path / "memdir").glob("*.tmp"))


def test_memory_concurrent_writes_not_lost(mem, tmp_path):
    path = str(tmp_path / "c.json")

    def _w(i):
        mem.MemoryStoreNode(config={"persist_path": path}).process({"input": {"key": f"k{i}", "value": i}})

    threads = [threading.Thread(target=_w, args=(i,)) for i in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(json.loads(Path(path).read_text())["default"]) == 25


def test_memory_record_key_stores_any_payload(mem, tmp_path):
    path = tmp_path / "r.json"
    node = mem.MemoryStoreNode(config={"persist_path": str(path), "namespace": "runs", "key": "last_route"})
    out = node.process({"input": {"tool_name": "inspect_run", "arguments": {}}})["output"]
    assert out.key == "last_route" and out.metadata["op"] == "set"
    assert json.loads(path.read_text()) == {"runs": {"last_route": {"tool_name": "inspect_run", "arguments": {}}}}
    # A real MemoryOp still wins over the record key.
    node.process({"input": {"key": "other", "value": 1}})
    assert node.process({"input": {"key": "other"}})["output"].value == 1
    # Without a record key, a dict that is not a MemoryOp is still rejected clearly.
    with pytest.raises(ValueError, match="key is required"):
        mem.MemoryStoreNode(config={"persist_path": str(path)}).process({"input": {"tool_name": "x"}})


def test_memory_backend_memory(mem):
    node = mem.MemoryStoreNode(config={"backend": "memory", "namespace": "t-mem"})
    node.process({"input": {"key": "a", "value": [1]}})
    assert node.process({"input": {"key": "a"}})["output"].value == [1]


# ── 8. agent_loop ─────────────────────────────────────────────────────────────

def _fake_llm(monkeypatch, replies):
    import app.core.ml.llm_client as llm_client

    seen = []

    def fake_chat(**kw):
        seen.append(kw)
        return {"content": replies.pop(0), "model": kw["model"], "base_url": "http://llm.test/v1"}

    monkeypatch.setattr(llm_client, "chat_completion", fake_chat)
    return seen


def test_agent_loop_calls_llm_and_answers(monkeypatch):
    al = _load("agent_loop")
    seen = _fake_llm(monkeypatch, ['<think>hmm</think>{"action": "final", "answer": "cats are here"}'])
    node = al.AgentLoopNode(config={"max_steps": 2, "model": "m1"})
    out = node.process({"goal": "find cats", "context": "cats are here"})["output"]
    assert out.mode == "llm" and out.final == "cats are here"
    assert out.metadata["llm_called"] is True and out.metadata["llm_calls"] == 1
    assert "cats are here" in seen[0]["messages"][1]["content"]
    assert seen[0]["model"] == "m1" and seen[0]["temperature"] == 0.0
    calls = node.take_external_calls()
    assert len(calls) == 1 and calls[0]["kind"] == "llm" and calls[0]["status"] == 200
    assert "extractive" not in al.AgentLoopNode.metadata.description.lower()


def test_agent_loop_tool_round_trip(monkeypatch, fake_tools):
    al = _load("agent_loop")
    seen = _fake_llm(monkeypatch, [
        '{"action": "final", "answer": "guess"}',
        '{"action": "call_tool", "tool": "list_nodes", "arguments": {"q": 1}}',
        '{"action": "final", "answer": "one node: x"}',
    ])
    node = al.AgentLoopNode(config={"tool_allowlist": ["list_nodes"], "require_tool_call": True})
    out = node.process({"goal": "how many nodes?"})["output"]
    assert out.final == "one node: x"
    assert fake_tools == [("list_nodes", {"q": 1})]
    assert out.metadata["tools_called"] == ["list_nodes"]
    assert [s["action"] for s in out.steps] == ["rejected_final", "call_tool", "final"]
    assert "Observation" in seen[2]["messages"][-1]["content"] and '"x"' in seen[2]["messages"][-1]["content"]


def test_agent_loop_refuses_mutating_and_unknown_tools(monkeypatch, fake_tools):
    al = _load("agent_loop")
    _fake_llm(monkeypatch, ['{"action": "call_tool", "tool": "install_plugin", "arguments": {}}',
                            '{"action": "final", "answer": "done"}'])
    with pytest.raises(PermissionError, match="allow_mutating"):
        al.AgentLoopNode(config={"tool_allowlist": ["install_plugin"]}).process({"goal": "x"})
    with pytest.raises(ValueError, match="unknown MCP tool"):
        al.AgentLoopNode(config={"tool_allowlist": ["nope"]}).process({"goal": "x"})
    # model asks for a tool outside the allowlist → refused observation, no call
    out = al.AgentLoopNode(config={"tool_allowlist": ["list_nodes"]}).process({"goal": "x"})["output"]
    assert fake_tools == [] and out.steps[0]["ok"] is False and out.final == "done"


def test_agent_loop_forces_final_after_max_steps(monkeypatch, fake_tools):
    al = _load("agent_loop")
    _fake_llm(monkeypatch, ['{"action": "call_tool", "tool": "list_nodes", "arguments": {}}',
                            "plain prose answer"])
    out = al.AgentLoopNode(config={"tool_allowlist": ["list_nodes"], "max_steps": 1}).process(
        {"goal": "x"})["output"]
    assert out.final == "plain prose answer" and out.steps[-1]["note"] == "forced after max_steps"


def test_agent_loop_requires_goal_and_surfaces_llm_errors(monkeypatch):
    al = _load("agent_loop")
    with pytest.raises(ValueError, match="goal"):
        al.AgentLoopNode().process({})
    import app.core.ml.llm_client as llm_client

    def boom(**kw):
        raise ConnectionError("no server")

    monkeypatch.setattr(llm_client, "chat_completion", boom)
    node = al.AgentLoopNode()
    with pytest.raises(RuntimeError, match="no server"):
        node.process({"goal": "x"})
    assert node.take_external_calls()[0]["error"] == "ConnectionError"


# ── 9. llm_chat zero values ───────────────────────────────────────────────────

def test_llm_chat_temperature_zero_passed(monkeypatch):
    lc = _load("llm_chat")
    seen = {}

    def fake_chat(**kw):
        seen.update(kw)
        return {"content": "ok"}

    import app.core.ml.llm_client as llm_client

    monkeypatch.setattr(llm_client, "chat_completion", fake_chat)
    node = lc.LlmChatNode(config={"provider": "openai_compat", "temperature": 0.0, "timeout_s": 5})
    assert node.process({"input": "hi"})["output"].content == "ok"
    assert seen["temperature"] == 0.0 and seen["timeout_s"] == 5.0


def test_memory_store_unwraps_canonical_payload_wrappers(mem, tmp_path):
    """F-06 payload contract: a python_code CodeResult (dict form after transfer) is unwrapped."""
    node = mem.MemoryStoreNode(config={"persist_path": str(tmp_path / "m.json")})
    node.process({"input": {"data": {"key": "w", "value": 7}, "metadata": {"python_code": {}}}})
    assert node.process({"input": "w"})["output"].value == 7
