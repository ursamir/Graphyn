#!/usr/bin/env python3
"""Scaffold Proposed (+ refinement-added) plugin packs from PLATFORM catalogs.

Creates PluginPackage/<Pack>/<plugin_name>/{plugin.toml,__init__.py,types.py,nodes.py}
for every Proposed node that does not already ship a loadable plugin.toml.

Stub process() returns correctly typed empty/minimal outputs; optional heavy
deps are never imported at module level. needs-api nodes raise structured errors.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "docs" / "PLUGIN_NODE_PLATFORM_CATALOG.json"
REFINEMENTS = REPO / "docs" / "PLUGIN_NODE_REFINEMENTS.json"

# Platform types living in app.models
APP_MODELS = {
    "DatasetArtifact": ("app.models.dataset_artifact", "DatasetArtifact"),
    "ModelArtifact": ("app.models.model_artifact", "ModelArtifact"),
    "FeatureArray": ("app.models.feature_array", "FeatureArray"),
    "AudioSample": ("app.models.audio_sample", "AudioSample"),
    "PredictionResult": ("app.models.prediction_result", "PredictionResult"),
    "TFLiteArtifact": ("app.models.tflite_artifact", "TFLiteArtifact"),
    "DeploymentArtifact": ("app.models.deployment_artifact", "DeploymentArtifact"),
}

# Types that already exist in Common plugins — we redefine lightweight copies
# locally for TypeCatalogue; ports use object/list for cross-plugin compat.
KNOWN_PLUGIN_TYPES = {
    "Chunk",
    "EmbeddingVector",
    "BranchResult",
    "ErrorEnvelope",
    "EvalReport",
    "ExperimentArtifact",
    "CaptionExportResult",
    "HttpResponse",
    "WebhookReceipt",
    "RedactionAudit",
    "StructuredDocument",
    "Transcript",
    "TriggerEvent",
    "CsvTableResult",
    "ObjectRef",
    "ObjectList",
    "SparseIndexRef",
    "VectorStoreRef",
}

NEEDS_API = {"mcu_flash_ota", "mcu_ondevice_metrics"}

OPTIONAL_DEPS_BY_HINT = {
    "ultralytics": ["ultralytics>=8.0"],
    "torch": ["torch>=2.0"],
    "tensorflow": ["tensorflow>=2.13"],
    "tflite": ["tflite-runtime>=2.14"],
    "onnxruntime": ["onnxruntime>=1.16"],
    "sentence-transformers": ["sentence-transformers>=2.2"],
    "faiss": ["faiss-cpu>=1.7"],
    "chromadb": ["chromadb>=0.4"],
    "opencv": ["opencv-python-headless>=4.8"],
    "httpx": ["httpx>=0.24"],
}


def load_nodes() -> list[dict[str, Any]]:
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    nodes = list(cat.get("nodes") or [])
    # Prefer refinement_added_nodes from catalog; fall back to refinements JSON
    added = list(cat.get("refinement_added_nodes") or [])
    if not added and REFINEMENTS.is_file():
        ref = json.loads(REFINEMENTS.read_text(encoding="utf-8"))
        added = list(ref.get("added_nodes") or [])
    # Dedup by node_type
    seen = {n["node_type"] for n in nodes}
    for n in added:
        if n["node_type"] not in seen:
            nodes.append(n)
            seen.add(n["node_type"])
    return nodes


def parse_pack(pack: str) -> tuple[str, str]:
    """Return (PackName, plugin_dir_name) from 'PluginPackage/TinyML/mcu_x/'."""
    parts = [p for p in pack.strip("/").split("/") if p]
    # PluginPackage, Pack, name
    if len(parts) >= 3:
        return parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], parts[1]
    return "Common", parts[-1] if parts else "unknown"


def parse_config_field(spec: str) -> dict[str, Any]:
    """Parse 'name:type=default' or 'name:type' into field info."""
    spec = spec.strip()
    if not spec:
        return {}
    m = re.match(
        r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
        r"(?::(?P<ty>[^=]+))?"
        r"(?:=(?P<default>.*))?$",
        spec,
    )
    if not m:
        return {"name": spec, "py_type": "str", "default": '""', "toml_type": "string", "toml_default": '""'}
    name = m.group("name")
    ty = (m.group("ty") or "str").strip()
    default_raw = m.group("default")
    return _map_config_type(name, ty, default_raw)


def _map_config_type(name: str, ty: str, default_raw: str | None) -> dict[str, Any]:
    ty_l = ty.lower().replace(" ", "")
    # list[str] etc.
    if ty_l.startswith("list"):
        py_type = "list"
        if default_raw is None or default_raw == "":
            default = "Field(default_factory=list)"
            toml_default = "[]"
        else:
            try:
                val = ast.literal_eval(default_raw)
                default = f"Field(default_factory=lambda: {val!r})"
                toml_default = json.dumps(val)
            except Exception:
                default = "Field(default_factory=list)"
                toml_default = "[]"
        return {
            "name": name,
            "py_type": py_type,
            "default": default,
            "toml_type": "array",
            "toml_default": toml_default,
            "field_kwargs": True,
        }
    if ty_l.startswith("dict"):
        if default_raw is None or default_raw in ("", "{}"):
            default = "Field(default_factory=dict)"
        else:
            try:
                val = ast.literal_eval(default_raw)
                default = f"Field(default_factory=lambda: {val!r})"
            except Exception:
                default = "Field(default_factory=dict)"
        return {
            "name": name,
            "py_type": "dict",
            "default": default,
            "toml_type": "object",
            "toml_default": "{}",
            "field_kwargs": True,
        }
    if ty_l in ("int", "integer"):
        d = 0 if default_raw is None or default_raw == "" else int(float(default_raw))
        return {"name": name, "py_type": "int", "default": repr(d), "toml_type": "integer", "toml_default": str(d)}
    if ty_l in ("float", "number"):
        d = 0.0 if default_raw is None or default_raw == "" else float(default_raw)
        return {"name": name, "py_type": "float", "default": repr(d), "toml_type": "number", "toml_default": str(d)}
    if ty_l in ("bool", "boolean"):
        if default_raw is None or default_raw == "":
            d = False
        else:
            d = str(default_raw).strip().lower() in ("1", "true", "yes", "on")
        return {
            "name": name,
            "py_type": "bool",
            "default": repr(d),
            "toml_type": "boolean",
            "toml_default": "true" if d else "false",
        }
    # str / everything else
    if default_raw is None:
        d = ""
    else:
        d = default_raw
    return {
        "name": name,
        "py_type": "str",
        "default": repr(d),
        "toml_type": "string",
        "toml_default": json.dumps(d),
    }


def extract_type_names(type_str: str) -> list[str]:
    """Extract CamelCase type names from a catalog type string."""
    names = re.findall(r"[A-Z][A-Za-z0-9]+", type_str or "")
    skip = {"NEW", "Any", "Optional", "None", "True", "False", "Union", "List", "Dict"}
    return [n for n in names if n not in skip]


def _split_top_level_union(s: str) -> list[str]:
    """Split on | not inside [...]."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in s:
        if ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "|" and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _sanitize_type_token(tok: str) -> str:
    tok = tok.strip().strip("[]").strip()
    # Strip accidental trailing brackets from bad splits
    tok = re.sub(r"[\[\]]+", "", tok)
    return tok


def port_data_type_expr(type_str: str) -> tuple[str, set[str], set[str]]:
    """Return (annotation expression, app_model_imports, local_type_names).

    For NEW / plugin-local types we use object / list to keep cross-plugin
    graph validation permissive. App models use concrete classes.
    """
    app_imports: set[str] = set()
    local_types: set[str] = set()
    raw = (type_str or "Any").strip()
    optional = "optional" in raw.lower()
    cleaned = re.sub(r"\bNEW\b", "", raw, flags=re.I)
    cleaned = re.sub(r"\boptional\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bmulti\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    def map_atomic(tok: str) -> str:
        tok = _sanitize_type_token(tok)
        if not tok or tok in ("Any", "object"):
            return "object"
        if tok == "str":
            return "str"
        if tok == "dict":
            return "dict"
        if tok in APP_MODELS:
            app_imports.add(tok)
            return tok
        if tok in ("None", "Optional", "Any", "Union", "List", "Dict"):
            return "object"
        if tok and tok[0].isupper():
            local_types.add(tok)
            return "object"
        return "object"

    def map_list_inner(inner: str) -> str:
        inner = inner.strip()
        # list may contain unions of types
        parts = _split_top_level_union(inner) if "|" in inner else [inner]
        atoms = []
        for p in parts:
            p = p.strip()
            # nested list unlikely; treat as atomic name
            if p.startswith("list[") and p.endswith("]"):
                map_list_inner(p[5:-1])
                atoms.append("list")
            else:
                atoms.append(map_atomic(p))
        for p in parts:
            name = _sanitize_type_token(p[5:-1] if p.startswith("list[") and p.endswith("]") else p)
            if name in APP_MODELS:
                app_imports.add(name)
                return f"list[{name}]"
        return "list"

    # Top-level unions first (handles list[A]|list[B])
    union_parts = _split_top_level_union(cleaned)
    if len(union_parts) > 1:
        saw_list = False
        for part in union_parts:
            part = part.strip()
            if part.startswith("list[") and part.endswith("]"):
                map_list_inner(part[5:-1])
                saw_list = True
            else:
                map_atomic(part)
        # Prefer bare list if any side is a list; else object
        expr = "list" if saw_list else "object"
        # If exactly one side is a concrete app model (non-list), keep object
        if optional:
            expr = f"{expr} | None"
        return expr, app_imports, local_types

    # Single list[...]
    m = re.match(r"^list\[(.*)\]$", cleaned.replace(" ", ""))
    if m or (cleaned.startswith("list[") and cleaned.endswith("]")):
        inner = m.group(1) if m else cleaned[5:-1]
        expr = map_list_inner(inner)
        if optional:
            expr = f"{expr} | None"
        return expr, app_imports, local_types

    expr = map_atomic(cleaned)
    if optional and "| None" not in expr:
        expr = f"{expr} | None" if expr != "object" else "object | None"
    return expr, app_imports, local_types


def snake_to_pascal(name: str) -> str:
    return "".join(p.capitalize() for p in name.split("_")) + "Node"


def title_label(node_type: str) -> str:
    return " ".join(p.capitalize() for p in node_type.split("_"))


def infer_optional_deps(node: dict[str, Any]) -> list[str]:
    blob = " ".join(
        [
            str(node.get("optional_dependencies_runtime") or ""),
            str(node.get("notes") or ""),
            str(node.get("purpose") or ""),
            node.get("node_type", ""),
        ]
    ).lower()
    deps: list[str] = []
    for key, pkgs in OPTIONAL_DEPS_BY_HINT.items():
        if key in blob:
            for p in pkgs:
                if p not in deps:
                    deps.append(p)
    # YOLO / vision
    if "yolo" in blob and "ultralytics>=8.0" not in deps:
        deps.append("ultralytics>=8.0")
        if "torch>=2.0" not in deps:
            deps.append("torch>=2.0")
    if node.get("node_type", "").startswith("tflm") or "tflite" in blob:
        if "tensorflow>=2.13" not in deps:
            deps.append("tensorflow>=2.13")
    return deps


def infer_runtime(node: dict[str, Any], opt_deps: list[str]) -> str:
    blob = str(node.get("optional_dependencies_runtime") or "").lower()
    if "runtime=isolated" in blob or opt_deps:
        # Heavy ML → isolated
        heavy = any(
            x.split(">=")[0] in ("torch", "tensorflow", "ultralytics", "sentence-transformers", "faiss-cpu", "chromadb")
            for x in opt_deps
        )
        if heavy or "runtime=isolated" in blob:
            return "inprocess"  # stubs run in-process; heavy deps remain optional
    return "inprocess"


def stub_return_expr(type_str: str, local_types: set[str]) -> str:
    """Python expression for a minimal typed stub output."""
    raw = (type_str or "Any").strip()
    cleaned = re.sub(r"\bNEW\b|\boptional\b|\bmulti\b", "", raw, flags=re.I).strip()
    if cleaned.startswith("list[") or cleaned.startswith("list ["):
        return "[]"
    if cleaned in ("str",):
        return '""'
    if cleaned in ("dict",):
        return "{}"
    if "ModelArtifact" in cleaned and "TFLite" not in cleaned and "Deployment" not in cleaned:
        return 'ModelArtifact(model_path=str(_out), labels=[], history={"stub": True}, metrics={})'
    if "DatasetArtifact" in cleaned:
        return 'DatasetArtifact(labels=[], input_shape=(), n_classes=0, metadata={"stub": True})'
    if "TFLiteArtifact" in cleaned:
        return 'TFLiteArtifact(model_path=str(_out), metadata={"stub": True})'
    if "DeploymentArtifact" in cleaned:
        return 'DeploymentArtifact(package_path=str(_out), target="stub", metadata={"stub": True})'
    if "FeatureArray" in cleaned:
        return "[]"  # often list[FeatureArray] already handled
    if "PredictionResult" in cleaned:
        return "[]"
    if "AudioSample" in cleaned:
        return "[]"
    # Local NEW type
    names = extract_type_names(cleaned)
    for n in names:
        if n in local_types or n not in APP_MODELS:
            if n in APP_MODELS:
                continue
            # Prefer constructing local type
            return f"{n}()"
    return "None"


def render_types_py(local_types: set[str], pack: str, node_type: str) -> str:
    lines = [
        f'"""Port types for {node_type} ({pack}).',
        "",
        "Do NOT use `from __future__ import annotations`.",
        '"""',
        "from typing import Any, Optional",
        "",
        "from pydantic import Field",
        "",
        "from app.core.nodes.ports import PortDataType",
        "",
        "",
    ]
    # Minimal fields for common NEW types
    FIELD_PRESETS: dict[str, list[str]] = {
        "McuSample": [
            'sample_id: str = ""',
            "payload: Any = None",
            'modality: str = "audio"',
            "label: Optional[str] = None",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "ImageSample": [
            'path: str = ""',
            "image: Any = None",
            "label: Optional[str] = None",
            "boxes: list = Field(default_factory=list)",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "VideoSample": [
            'path: str = ""',
            "frames: list = Field(default_factory=list)",
            "fps: float = 0.0",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "VisionDatasetArtifact": [
            'root: str = ""',
            'task: str = "detect"',
            "names: list[str] = Field(default_factory=list)",
            'yaml_path: str = ""',
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "DetectionResult": [
            "boxes: list = Field(default_factory=list)",
            "scores: list = Field(default_factory=list)",
            "labels: list = Field(default_factory=list)",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "TrackResult": [
            "tracks: list = Field(default_factory=list)",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "AnnotationExport": [
            'path: str = ""',
            'format: str = ""',
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "Chunk": [
            'text: str = ""',
            'source: str = ""',
            "page: Optional[int] = None",
            'chunk_id: str = ""',
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "RawDocument": [
            'path: str = ""',
            'text: str = ""',
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "EmbeddingVector": [
            "embedding: Any = None",
            'source_path: str = ""',
            'label: str = ""',
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "VectorStoreRef": [
            'backend: str = ""',
            'path: str = ""',
            'collection: str = ""',
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "RetrievalHit": [
            'chunk_id: str = ""',
            'text: str = ""',
            "score: float = 0.0",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "AssembledPrompt": [
            'system: str = ""',
            'user: str = ""',
            "messages: list = Field(default_factory=list)",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "RagAnswer": [
            'answer: str = ""',
            "citations: list = Field(default_factory=list)",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "RagEvalReport": [
            "metrics: dict[str, Any] = Field(default_factory=dict)",
            "passed: bool = False",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "KnowledgeGraphFragment": [
            "entities: list = Field(default_factory=list)",
            "relations: list = Field(default_factory=list)",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "SparseIndexRef": [
            'path: str = ""',
            'backend: str = "bm25"',
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "ArenaEstimate": [
            "arena_bytes: int = 0",
            "peak_bytes: int = 0",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "TflmSupportReport": [
            "supported: bool = True",
            "unsupported_ops: list[str] = Field(default_factory=list)",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "FlashReceipt": [
            'status: str = "needs-api"',
            'device_id: str = ""',
            "message: str = \"MCU flash/OTA requires Devices API — not faked.\"",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "OnDeviceMetrics": [
            'status: str = "needs-api"',
            "metrics: dict[str, Any] = Field(default_factory=dict)",
            "message: str = \"On-device metrics require Devices API — not faked.\"",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "DatasetHealthReport": [
            "ok: bool = True",
            "issues: list = Field(default_factory=list)",
            "stats: dict[str, Any] = Field(default_factory=dict)",
        ],
        "SceneBoundary": [
            "start_s: float = 0.0",
            "end_s: float = 0.0",
            "score: float = 0.0",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "CaptionRecord": [
            'text: str = ""',
            "start_s: float = 0.0",
            "end_s: float = 0.0",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "AvAlignedSample": [
            'audio_path: str = ""',
            'video_path: str = ""',
            "offset_s: float = 0.0",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "ToolCallRequest": [
            'tool: str = ""',
            "arguments: dict[str, Any] = Field(default_factory=dict)",
        ],
        "ToolCallResult": [
            'tool: str = ""',
            "ok: bool = False",
            "result: Any = None",
            "error: Optional[str] = None",
        ],
        "AgentResult": [
            'final: str = ""',
            "steps: list = Field(default_factory=list)",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "MemoryRecord": [
            'key: str = ""',
            "value: Any = None",
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "MemoryOp": [
            'op: str = "get"',
            'key: str = ""',
            "value: Any = None",
        ],
        "GuardrailHit": [
            'rule: str = ""',
            'severity: str = ""',
            "score: float = 0.0",
        ],
        "ChatMessage": [
            'role: str = "user"',
            'content: str = ""',
        ],
        "DatasetDiffReport": [
            "added: int = 0",
            "removed: int = 0",
            "changed: int = 0",
            "details: dict[str, Any] = Field(default_factory=dict)",
        ],
        "DriftReport": [
            "drifted: bool = False",
            "scores: dict[str, Any] = Field(default_factory=dict)",
        ],
        "ModelCardArtifact": [
            'path: str = ""',
            "content: dict[str, Any] = Field(default_factory=dict)",
        ],
        "AbAssignment": [
            'variant: str = "control"',
            'unit_id: str = ""',
        ],
        "CanaryDecision": [
            "promote: bool = False",
            "reason: str = \"\"",
            "metrics: dict[str, Any] = Field(default_factory=dict)",
        ],
        "ShipPackageRef": [
            'package_id: str = ""',
            'path: str = ""',
            'state: str = "created"',
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "FeatureStoreRef": [
            'path: str = ""',
            'feature_set: str = ""',
            "metadata: dict[str, Any] = Field(default_factory=dict)",
        ],
        "ChecksumRecord": [
            'algo: str = "sha256"',
            'digest: str = ""',
            'path: str = ""',
        ],
    }
    for tname in sorted(local_types):
        fields = FIELD_PRESETS.get(
            tname,
            [
                'status: str = "stub"',
                "metadata: dict[str, Any] = Field(default_factory=dict)",
                "payload: Any = None",
            ],
        )
        lines.append(f"class {tname}(PortDataType):")
        for f in fields:
            lines.append(f"    {f}")
        lines.append("")
        lines.append("")
    if not local_types:
        lines.append("# No plugin-local PortDataType subclasses required.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_plugin_toml(
    node: dict[str, Any],
    plugin_name: str,
    opt_deps: list[str],
    runtime: str,
    config_fields: list[dict[str, Any]],
    has_types: bool,
) -> str:
    nt = node["node_type"]
    desc = (node.get("purpose") or nt).replace('"', "'")
    tags = [parse_pack(node.get("pack", ""))[0].lower(), nt.split("_")[0], "stub"]
    entry = '["types.py", "nodes.py"]' if has_types else '["nodes.py"]'
    lines = [
        "[plugin]",
        f'name             = "{plugin_name.replace("_", "-")}"',
        'version          = "0.1.0"',
        f'description      = "{desc}"',
        'author           = "Graphyn Plugins"',
        'platform_version = ">=0.0"',
        f"entry_points     = {entry}",
        'license          = "MIT"',
        "",
        f"tags = {json.dumps(tags)}",
        "",
        "dependencies = [",
        '    "numpy>=1.24",',
        "]",
        "",
    ]
    if opt_deps:
        lines.append("optional_dependencies = [")
        for d in opt_deps:
            lines.append(f'    "{d}",')
        lines.append("]")
        lines.append("")
    lines.append(f'runtime = "{runtime}"')
    lines.append(f"node_types = [\"{nt}\"]")
    lines.append("")
    lines.append(f"[config_schema.{nt}]")
    # Always include stub flag
    lines.append(
        'stub = { type = "boolean", title = "Stub mode", default = true, '
        'description = "When true (default), return typed minimal outputs without heavy ML deps." }'
    )
    for f in config_fields:
        if f["name"] == "stub":
            continue
        title = f["name"].replace("_", " ").capitalize()
        if f["toml_type"] == "array":
            lines.append(
                f'{f["name"]} = {{ type = "array", title = "{title}", default = {f["toml_default"]}, '
                f'description = "{title}." }}'
            )
        elif f["toml_type"] == "object":
            lines.append(
                f'{f["name"]} = {{ type = "object", title = "{title}", default = {{}}, '
                f'description = "{title}." }}'
            )
        else:
            lines.append(
                f'{f["name"]} = {{ type = "{f["toml_type"]}", title = "{title}", '
                f'default = {f["toml_default"]}, description = "{title}." }}'
            )
    lines.append("")
    return "\n".join(lines)


def render_nodes_py(
    node: dict[str, Any],
    config_fields: list[dict[str, Any]],
    local_types: set[str],
    app_imports: set[str],
) -> str:
    nt = node["node_type"]
    cls = snake_to_pascal(nt)
    pack_name, _ = parse_pack(node.get("pack", ""))
    purpose = (node.get("purpose") or nt).replace('"', "'")
    category = node.get("category") or "Processing"
    label = title_label(nt)

    inputs = node.get("inputs") or []
    outputs = node.get("outputs") or []

    # Collect port exprs
    in_ports = []
    out_ports = []
    all_app: set[str] = set(app_imports)
    all_local: set[str] = set(local_types)

    for p in inputs:
        expr, ai, lt = port_data_type_expr(p.get("type", "Any"))
        all_app |= ai
        all_local |= lt
        req = "optional" not in (p.get("type") or "").lower()
        # Source nodes may have empty inputs
        in_ports.append(
            {
                "name": p.get("name") or "input",
                "expr": expr,
                "required": req,
                "desc": p.get("type") or "",
            }
        )
    for p in outputs:
        expr, ai, lt = port_data_type_expr(p.get("type", "Any"))
        all_app |= ai
        all_local |= lt
        out_ports.append(
            {
                "name": p.get("name") or "output",
                "expr": expr,
                "desc": p.get("type") or "",
                "raw_type": p.get("type") or "Any",
            }
        )

    # Imports
    lines = [
        f'"""{cls} — {purpose}',
        "",
        "Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.",
        "Default config.stub=True returns typed minimal outputs without heavy deps.",
        '"""',
        "from __future__ import annotations",
        "",
        "import importlib",
        "import logging",
        "from pathlib import Path",
        "from typing import ClassVar, Any",
        "from pydantic import Field",
        "",
        "from app.core.nodes.base import Node",
        "from app.core.nodes.config import NodeConfig",
        "from app.core.nodes.metadata import NodeMetadata",
        "from app.core.nodes.ports import InputPort, OutputPort",
        "",
    ]
    for name in sorted(all_app):
        mod, cls_name = APP_MODELS[name]
        lines.append(f"from {mod} import {cls_name}")
    if all_app:
        lines.append("")

    if all_local:
        lines.append("try:")
        lines.append('    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__')
        lines.append(f'    _types = importlib.import_module(f"{{_pkg}}.types")')
        lines.append("except (ImportError, ModuleNotFoundError):")
        lines.append("    try:")
        lines.append(f'        _types = importlib.import_module("{nt}.types")')
        lines.append("    except (ImportError, ModuleNotFoundError):")
        lines.append("        from . import types as _types  # type: ignore")
        lines.append("")
        for tname in sorted(all_local):
            lines.append(f"{tname} = _types.{tname}")
        lines.append("")

    lines.append("log = logging.getLogger(__name__)")
    lines.append("")
    lines.append("")
    lines.append(f"class {cls}(Node):")
    lines.append(f'    """{purpose}"""')
    lines.append("")
    lines.append(f'    node_type: ClassVar[str] = "{nt}"')
    lines.append("")
    lines.append("    metadata: ClassVar[NodeMetadata] = NodeMetadata(")
    lines.append(f'        node_type="{nt}",')
    lines.append(f'        label="{label}",')
    lines.append(f'        description="{purpose}",')
    lines.append(f'        category="{category}",')
    lines.append('        version="0.1.0",')
    lines.append(f'        tags=["{pack_name.lower()}", "stub"],')
    lines.append("        requires_gpu=False,")
    lines.append("        supports_cpu=True,")
    lines.append("        supports_edge=True,")
    lines.append("        deterministic=True,")
    lines.append("        cacheable=False,")
    lines.append("    )")
    lines.append("")

    # input ports
    if in_ports:
        lines.append("    input_ports: ClassVar[dict[str, InputPort]] = {")
        for p in in_ports:
            req = "True" if p["required"] else "False"
            # optional ports must accept None
            expr = p["expr"]
            if not p["required"] and "| None" not in expr and expr != "object":
                expr = f"{expr} | None"
            elif not p["required"] and expr == "object":
                expr = "object | None"
            lines.append(
                f'        "{p["name"]}": InputPort('
                f'name="{p["name"]}", data_type={expr}, required={req}, '
                f'description="{p["desc"]}"),'
            )
        lines.append("    }")
    else:
        lines.append("    input_ports: ClassVar[dict[str, InputPort]] = {}")
    lines.append("")

    lines.append("    output_ports: ClassVar[dict[str, OutputPort]] = {")
    if out_ports:
        for p in out_ports:
            lines.append(
                f'        "{p["name"]}": OutputPort('
                f'name="{p["name"]}", data_type={p["expr"]}, '
                f'description="{p["desc"]}"),'
            )
    else:
        lines.append(
            '        "output": OutputPort(name="output", data_type=object, description="stub"),'
        )
    lines.append("    }")
    lines.append("")

    # Config
    lines.append("    class Config(NodeConfig):")
    lines.append(
        '        stub: bool = Field(default=True, title="Stub mode", '
        'description="When true, return typed minimal outputs without heavy ML deps.")'
    )
    for f in config_fields:
        if f["name"] == "stub":
            continue
        title = f["name"].replace("_", " ").capitalize()
        if f.get("field_kwargs"):
            # default already is Field(...)
            lines.append(f'        {f["name"]}: {f["py_type"]} = {f["default"]}')
        else:
            lines.append(
                f'        {f["name"]}: {f["py_type"]} = Field('
                f'default={f["default"]}, title="{title}", description="{title}.")'
            )
    lines.append("")

    # process
    lines.append("    def process(self, inputs=None, **kwargs):")
    lines.append('        """Stub-capable process — real backends optional."""')
    lines.append("        if inputs is None:")
    lines.append("            inputs = kwargs")
    lines.append("        if not isinstance(inputs, dict):")
    lines.append('            inputs = {"input": inputs}')
    lines.append("")

    if nt in NEEDS_API:
        lines.append("        # Honesty stub — never fake device flash / on-device metrics.")
        lines.append("        dry = bool(getattr(self.config, 'dry_run', True))")
        if nt == "mcu_flash_ota":
            lines.append("        receipt = FlashReceipt(")
            lines.append('            status="needs-api",')
            lines.append('            device_id=str(getattr(self.config, "device_id", "") or ""),')
            lines.append(
                '            message="MCU flash/OTA requires Devices API — mark needs-api; never fake device control.",'
            )
            lines.append('            metadata={"dry_run": dry, "node_type": "mcu_flash_ota"},')
            lines.append("        )")
            lines.append("        if not dry:")
            lines.append(
                '            raise RuntimeError(receipt.message + " Set config.dry_run=True for honesty stub.")'
            )
            lines.append('        log.warning("mcu_flash_ota: %s", receipt.message)')
            lines.append('        return {"output": receipt}')
        else:
            lines.append("        metrics = OnDeviceMetrics(")
            lines.append('            status="needs-api",')
            lines.append("            metrics={},")
            lines.append(
                '            message="On-device metrics require Devices API — not faked.",'
            )
            lines.append('            metadata={"dry_run": dry, "node_type": "mcu_ondevice_metrics"},')
            lines.append("        )")
            lines.append("        if not dry:")
            lines.append(
                '            raise RuntimeError(metrics.message + " Set config.dry_run=True for honesty stub.")'
            )
            lines.append('        log.warning("mcu_ondevice_metrics: %s", metrics.message)')
            lines.append('        return {"output": metrics}')
    else:
        lines.append("        stub = bool(getattr(self.config, 'stub', True))")
        lines.append("        out_dir = Path('workspace/artifacts') / '" + pack_name.lower() + f"' / '{nt}'")
        lines.append("        if stub:")
        lines.append("            out_dir.mkdir(parents=True, exist_ok=True)")
        lines.append("            _out = out_dir / 'stub'")
        # Build return dict
        if len(out_ports) <= 1:
            p = out_ports[0] if out_ports else {"name": "output", "raw_type": "Any"}
            ret = stub_return_expr(p.get("raw_type", "Any"), all_local)
            # Ensure local type names available for constructor
            lines.append(f"            result = {ret}")
            lines.append(f'            return {{"{p["name"]}": result}}')
        else:
            lines.append("            result = {")
            for p in out_ports:
                ret = stub_return_expr(p.get("raw_type", "Any"), all_local)
                lines.append(f'                "{p["name"]}": {ret},')
            lines.append("            }")
            lines.append("            return result")
        lines.append("        # Non-stub: attempt real backend; fall back with install hint")
        lines.append("        try:")
        lines.append("            return self._process_real(inputs)")
        lines.append("        except ImportError as exc:")
        lines.append(
            f'            raise ImportError('
            f'f"{nt}: optional dependency missing ({{exc}}). '
            f'Install plugin optional_dependencies or set config.stub=True.") from exc'
        )
        lines.append("")
        lines.append("    def _process_real(self, inputs: dict):")
        lines.append('        """Override point for richer backends; default = stub path."""')
        lines.append("        # Keep default identical to stub so unit tests stay offline.")
        lines.append("        prev = self.config.stub")
        lines.append("        object.__setattr__(self.config, 'stub', True) if hasattr(self.config, 'model_copy') else None")
        lines.append("        try:")
        lines.append("            self.config.stub = True  # type: ignore[misc]")
        lines.append("        except Exception:")
        lines.append("            pass")
        lines.append("        try:")
        lines.append("            # Re-enter stub branch")
        lines.append("            out_dir = Path('workspace/artifacts') / '" + pack_name.lower() + f"' / '{nt}'")
        lines.append("            out_dir.mkdir(parents=True, exist_ok=True)")
        lines.append("            _out = out_dir / 'stub'")
        if len(out_ports) <= 1:
            p = out_ports[0] if out_ports else {"name": "output", "raw_type": "Any"}
            ret = stub_return_expr(p.get("raw_type", "Any"), all_local)
            lines.append(f"            return {{\"{p['name']}\": {ret}}}")
        else:
            lines.append("            return {")
            for p in out_ports:
                ret = stub_return_expr(p.get("raw_type", "Any"), all_local)
                lines.append(f'                "{p["name"]}": {ret},')
            lines.append("            }")
        lines.append("        finally:")
        lines.append("            try:")
        lines.append("                self.config.stub = prev  # type: ignore[misc]")
        lines.append("            except Exception:")
        lines.append("                pass")

    lines.append("")
    return "\n".join(lines)


def render_init(cls_name: str, local_types: set[str]) -> str:
    lines = [f"from .nodes import {cls_name}"]
    exports = [cls_name]
    if local_types:
        lines.append(f"from .types import {', '.join(sorted(local_types))}")
        exports.extend(sorted(local_types))
    lines.append("")
    lines.append(f"__all__ = {exports!r}")
    lines.append("")
    return "\n".join(lines)


def scaffold_node(node: dict[str, Any], *, force: bool = False) -> Path | None:
    pack_name, plugin_dir = parse_pack(node.get("pack") or f"PluginPackage/Common/{node['node_type']}/")
    dest = REPO / "PluginPackage" / pack_name / plugin_dir
    toml_path = dest / "plugin.toml"
    if toml_path.is_file() and not force:
        return None

    config_fields = [parse_config_field(c) for c in (node.get("config") or [])]
    config_fields = [f for f in config_fields if f.get("name")]

    # Collect types from ports
    app_imports: set[str] = set()
    local_types: set[str] = set()
    for p in (node.get("inputs") or []) + (node.get("outputs") or []):
        _, ai, lt = port_data_type_expr(p.get("type", "Any"))
        app_imports |= ai
        local_types |= lt

    # needs-api must have their types
    if node["node_type"] == "mcu_flash_ota":
        local_types.add("FlashReceipt")
    if node["node_type"] == "mcu_ondevice_metrics":
        local_types.add("OnDeviceMetrics")

    opt_deps = infer_optional_deps(node)
    runtime = infer_runtime(node, opt_deps)
    has_types = bool(local_types)

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "types.py").write_text(render_types_py(local_types, pack_name, node["node_type"]), encoding="utf-8")
    (dest / "nodes.py").write_text(
        render_nodes_py(node, config_fields, local_types, app_imports), encoding="utf-8"
    )
    cls = snake_to_pascal(node["node_type"])
    (dest / "__init__.py").write_text(render_init(cls, local_types), encoding="utf-8")
    (dest / "plugin.toml").write_text(
        render_plugin_toml(node, plugin_dir, opt_deps, runtime, config_fields, has_types=True),
        encoding="utf-8",
    )
    return dest


def main() -> int:
    nodes = load_nodes()
    proposed = [n for n in nodes if n.get("status") == "Proposed"]
    # Also scaffold any refinement-added that might be marked differently
    force = "--force" in sys.argv
    created = []
    skipped = []
    for n in proposed:
        # Skip if already has plugin.toml under the pack path
        pack = n.get("pack") or ""
        pack_name, plugin_dir = parse_pack(pack)
        existing = REPO / "PluginPackage" / pack_name / plugin_dir / "plugin.toml"
        if existing.is_file() and not force:
            skipped.append(n["node_type"])
            continue
        path = scaffold_node(n, force=force)
        if path:
            created.append(n["node_type"])
        else:
            skipped.append(n["node_type"])

    print(f"created={len(created)} skipped={len(skipped)} proposed={len(proposed)}")
    for nt in created:
        print(f"  + {nt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
