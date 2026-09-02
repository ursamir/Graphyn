"""PythonCodeNode — restricted exec of config.source (no os.system/subprocess/network by default)."""
from __future__ import annotations

import ast
import builtins
import importlib
import json
import logging
import math
from pathlib import Path
from typing import Any, ClassVar

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("python_code.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

CodeResult = _types.CodeResult
log = logging.getLogger(__name__)

_MAX_SOURCE = 20000

_DISALLOWED_NAMES = frozenset({
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "ctypes",
    "importlib", "multiprocessing", "threading", "signal", "inspect",
    "code", "codeop", "compile", "eval", "exec", "open", "__import__",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "memoryview", "breakpoint", "input", "help", "exit", "quit",
    "httpx", "requests", "urllib", "aiohttp", "ftplib", "smtplib",
})

_DISALLOWED_ATTRS = frozenset({
    "system", "popen", "Popen", "run", "call", "check_output",
    "urlopen", "urlretrieve", "Request", "spawn", "fork",
})

_ALLOWED_IMPORTS = frozenset({"json", "math", "re", "datetime", "itertools", "functools", "collections", "decimal", "statistics"})


class RestrictedCodeError(RuntimeError):
    pass


def _validate_source(tree: ast.AST, *, allow_network: bool, allowed_paths: list[str]) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            else:
                names = [(node.module or "").split(".")[0]]
            for n in names:
                if not n:
                    continue
                if n in _DISALLOWED_NAMES or n not in _ALLOWED_IMPORTS:
                    if n in {"httpx", "requests", "urllib", "aiohttp"} and allow_network:
                        continue
                    raise RestrictedCodeError(f"Import of {n!r} is not allowed in python_code.")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in {"eval", "exec", "compile", "__import__"}:
                raise RestrictedCodeError(f"Call to {func.id}() is not allowed.")
            if isinstance(func, ast.Name) and func.id == "open" and not allowed_paths:
                raise RestrictedCodeError("open() is not allowed unless allowed_paths is set.")
            if isinstance(func, ast.Attribute) and func.attr in _DISALLOWED_ATTRS:
                raise RestrictedCodeError(f"Call to .{func.attr}() is not allowed.")
            if isinstance(func, ast.Attribute) and func.attr == "system":
                raise RestrictedCodeError("os.system is not allowed.")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise RestrictedCodeError("Dunder attribute access is not allowed in python_code.")
        if isinstance(node, ast.Name) and node.id in {"__builtins__", "__loader__", "__spec__"}:
            raise RestrictedCodeError(f"Name {node.id!r} is not allowed.")


def _safe_open(allowed_paths: list[str]):
    allowed = [str(Path(p).resolve()) for p in allowed_paths if p]

    def _open(file, mode="r", *args, **kwargs):
        path = Path(str(file)).resolve()
        mode_s = str(mode)
        if any(c in mode_s for c in ("w", "a", "x", "+")):
            raise RestrictedCodeError("python_code: write modes are not allowed for open().")
        if not allowed:
            raise RestrictedCodeError("python_code: open() requires config.allowed_paths.")
        ok = False
        for root in allowed:
            try:
                path.relative_to(root)
                ok = True
                break
            except ValueError:
                if str(path) == root:
                    ok = True
                    break
        if not ok:
            raise RestrictedCodeError(f"python_code: path {path} is not under allowed_paths.")
        return builtins.open(file, mode, *args, **kwargs)

    return _open


class PythonCodeNode(Node):
    node_type: ClassVar[str] = "python_code"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="python_code",
        label="Python Code",
        description="Restricted exec of a source string. Define process(inputs, config) or set output.",
        category="Transform",
        version="1.0.0",
        tags=["python", "code", "workflow", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object | None, required=False, description="Inputs payload"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="Code result"),
    }

    class Config(NodeConfig):
        source: str = ""
        allowed_paths: list = []
        allow_network: bool = False

    def process(self, inputs):
        source = self.config.source or ""
        if len(source) > _MAX_SOURCE:
            raise RestrictedCodeError("python_code source exceeds maximum length.")
        if not source.strip():
            payload = inputs.get("input") if isinstance(inputs, dict) else inputs
            return {"output": CodeResult(data=payload, metadata={"empty_source": True})}
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as exc:
            raise RestrictedCodeError(f"Syntax error in python_code: {exc}") from exc
        allowed_paths = [str(p) for p in (self.config.allowed_paths or [])]
        _validate_source(tree, allow_network=bool(self.config.allow_network), allowed_paths=allowed_paths)

        safe_builtins = {
            "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
            "enumerate": enumerate, "float": float, "int": int, "len": len,
            "list": list, "max": max, "min": min, "range": range, "repr": repr,
            "reversed": reversed, "round": round, "set": set, "sorted": sorted,
            "str": str, "sum": sum, "tuple": tuple, "zip": zip, "isinstance": isinstance,
            "None": None, "True": True, "False": False,
            "print": print,
        }
        if allowed_paths:
            safe_builtins["open"] = _safe_open(allowed_paths)

        ns: dict[str, Any] = {
            "__builtins__": safe_builtins,
            "inputs": inputs if isinstance(inputs, dict) else {"input": inputs},
            "config": {
                "source": None,
                "allowed_paths": list(allowed_paths),
                "allow_network": bool(self.config.allow_network),
            },
            "output": None,
            "json": json,
            "math": math,
        }
        compiled = compile(tree, "<python_code>", "exec")
        exec(compiled, ns, ns)  # noqa: S102 — AST-validated sandbox
        result: Any
        proc = ns.get("process")
        if callable(proc):
            result = proc(ns["inputs"], ns["config"])
        else:
            result = ns.get("output")
        if isinstance(result, dict) and set(result.keys()) <= {"output"} | set(result.keys()) and "output" in result and len(result) == 1:
            result = result["output"]
        return {"output": CodeResult(data=result, metadata={})}
