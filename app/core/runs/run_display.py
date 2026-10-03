# app/core/runs/run_display.py
"""
Bounded Context:  BC6 — Observability & Storage (run presentation)
Responsibility:   Human display names for runs ("Speech commands E2E ·
                  preprocess · yes") derived from graph metadata, the
                  example/template a generic graph came from, node
                  composition and the dataset_ingest label folder.
Owns:             run_display_name(), graph_family_and_phase(),
                  ingest_label_hint(), humanize_identifier(),
                  model_name_slug(); the example-graph signature index.
Public Surface:   run_display_name, graph_family_and_phase, ingest_label_hint,
                  humanize_identifier, model_name_slug
Must NOT:         Import app.domain / app.api; mutate runs or graphs;
                  change ``graph_name`` (display only).
Dependencies:     stdlib (json, re, pathlib, functools);
                  app.core.templates.example_templates (lazy).
Reason To Change: Naming heuristics or template metadata keys
                  (title/group/phase/step_title/source_example) change.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_ACRONYMS = frozenset(
    {"asr", "llm", "crm", "rag", "pii", "kws", "tflite", "onnx", "vad", "e2e",
     "mlops", "gpu", "ml", "ai", "cnn", "mfcc", "api", "csv", "mcp"}
)
_PHASES = {
    "preprocess": "preprocess",
    "preprocessing": "preprocess",
    "prep": "preprocess",
    "train": "train",
    "training": "train",
    "infer": "infer",
    "inference": "infer",
    "eval": "evaluate",
    "evaluate": "evaluate",
    "evaluation": "evaluate",
    "export": "export",
    "deploy": "deploy",
    "ingest": "ingest",
}
_GENERIC_TOKENS = frozenset({"pipeline", "graph", "ml", "untitled", "new", "copy", "draft"})
_GENERIC_NAMES = frozenset({"", "pipeline", "graph", "untitled", "new-pipeline", "new_pipeline", "my-pipeline"})


def humanize_identifier(raw: str) -> str:
    """``speech_commands_e2e`` → ``Speech commands E2E``."""
    words = [w for w in re.split(r"[-_\s]+", str(raw or "")) if w]
    out: list[str] = []
    for i, w in enumerate(words):
        low = w.lower()
        if low in _ACRONYMS:
            out.append(low.upper())
        elif i == 0:
            out.append(low[:1].upper() + low[1:])
        else:
            out.append(low)
    return " ".join(out)


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[-_\s]+", str(name or "").lower()) if t]


def graph_family_and_phase(name: str) -> tuple[str, str | None, list[str]]:
    """Split ``speech_commands_e2e_preprocess_down`` → (family, phase, rest)."""
    toks = _tokens(name)
    for i, tok in enumerate(toks):
        if tok in _PHASES and i > 0:
            family = [t for t in toks[:i] if t not in _GENERIC_TOKENS]
            rest = [t for t in toks[i + 1 :] if t not in _GENERIC_TOKENS]
            return "_".join(family), _PHASES[tok], rest
    family = [t for t in toks if t not in _GENERIC_TOKENS]
    return "_".join(family), None, []


def ingest_label_hint(path: str | None) -> str | None:
    """Return the label folder a dataset_ingest path ends in, if any.

    ``workspace/datasets/input/<dataset>/<label>`` and
    ``workspace/datasets/output/<project>/<version>/<split>/<label>`` end in
    a label folder; a dataset root does not.
    """
    if not isinstance(path, str) or not path.strip():
        return None
    parts = [p for p in path.replace("\\", "/").strip("/").split("/") if p and p != "latest"]
    if "datasets" in parts:
        idx = parts.index("datasets")
        tail = parts[idx + 1 :]
        if len(tail) >= 3 and tail[0] == "input":
            return tail[-1]
        if len(tail) >= 5 and tail[0] == "output":
            return tail[-1]
        return None
    if "data" in parts:
        tail = parts[parts.index("data") + 1 :]
        if len(tail) == 1:
            return tail[0]
    return None


def _graph_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    return [n for n in (nodes or []) if isinstance(n, dict)]


def _node_type(node: dict[str, Any]) -> str:
    return str(node.get("node_type") or node.get("type") or "").replace("Isolated_", "")


def _ingest_paths(graph: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for node in _graph_nodes(graph):
        if "ingest" in _node_type(node).lower():
            cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
            raw = cfg.get("path") or cfg.get("manifest_path")
            if isinstance(raw, str) and raw.strip():
                out.append(raw)
    return out


def _signature(graph: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(_node_type(n) for n in _graph_nodes(graph)))


@lru_cache(maxsize=1)
def _example_signature_index() -> dict[tuple[str, ...], list[tuple[str, str]]]:
    """Map node-type signature → [(example folder, graph file stem)]."""
    index: dict[tuple[str, ...], list[tuple[str, str]]] = {}
    try:
        from app.core.templates.example_templates import examples_dir

        root = examples_dir()
        for path in sorted(root.glob("*/*.graph.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            index.setdefault(_signature(data), []).append(
                (path.parent.name, path.name[: -len(".graph.json")])
            )
    except Exception:
        return {}
    return index


def _family_from_example_folder(folder: str) -> str:
    return re.sub(r"^\d+[_-]", "", folder or "")


def _phase_from_file_stem(stem: str) -> str | None:
    _fam, phase, _rest = graph_family_and_phase(stem)
    if phase:
        return phase
    for tok in _tokens(stem):
        if tok in _PHASES:
            return _PHASES[tok]
    return None


def _phase_from_composition(graph: dict[str, Any]) -> str | None:
    types = [_node_type(n).lower() for n in _graph_nodes(graph)]
    if any("trainer" in t or t == "train" for t in types):
        return "train"
    if any("inference" in t or "infer" in t or "predict" in t for t in types):
        return "infer"
    if any("export" in t for t in types) and any("ingest" in t for t in types):
        return "preprocess"
    return None


def _composition_title(graph: dict[str, Any]) -> str:
    types = [_node_type(n) for n in _graph_nodes(graph)]
    if not types:
        return "Pipeline"
    first = humanize_identifier(types[0])
    if len(types) == 1:
        return first
    return f"{first} → {humanize_identifier(types[-1])}"


def _resolve_family_phase(graph: dict[str, Any], graph_name: str) -> tuple[str | None, str | None, list[str]]:
    meta = graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {}
    name = str(graph_name or meta.get("name") or "").strip()
    phase_meta = meta.get("phase")
    step_title = meta.get("step_title")
    group = meta.get("group")
    family: str | None = None
    phase: str | None = None
    rest: list[str] = []
    if name and name.lower() not in _GENERIC_NAMES:
        family, phase, rest = graph_family_and_phase(name)
    if not family and isinstance(group, str) and group.strip():
        family = group.strip()
    src = meta.get("source_example") or meta.get("template") or meta.get("template_id")
    if (not family or not phase) and isinstance(src, str) and src.strip():
        src_path = Path(src.strip())
        folder = src_path.parent.name if src_path.suffix else src_path.name
        stem = src_path.name.split(".")[0] if src_path.suffix else ""
        if not family:
            fam2, ph2, _r = graph_family_and_phase(_family_from_example_folder(folder) or stem)
            family = fam2 or None
            phase = phase or ph2
        if not phase and stem:
            phase = _phase_from_file_stem(stem)
    if not family:
        hits = _example_signature_index().get(_signature(graph)) or []
        if hits:
            folder, stem = hits[0]
            family = graph_family_and_phase(_family_from_example_folder(folder))[0] or None
            phase = phase or _phase_from_file_stem(stem)
    if isinstance(step_title, str) and step_title.strip():
        phase = step_title.strip()
    elif not phase and isinstance(phase_meta, str) and phase_meta.strip() and not phase_meta.strip().isdigit():
        phase = phase_meta.strip()
    if not phase:
        phase = _phase_from_composition(graph)
    return family, phase, rest


def run_display_name(graph: dict[str, Any] | None, graph_name: str | None = None) -> str:
    """Human run title; never empty. ``graph_name`` stays the machine id."""
    graph = graph if isinstance(graph, dict) else {}
    meta = graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {}
    name = str(graph_name or meta.get("name") or "").strip()
    title = meta.get("title")
    labels = [h for h in (ingest_label_hint(p) for p in _ingest_paths(graph)) if h]
    label = labels[0] if labels else None

    if isinstance(title, str) and title.strip():
        out = title.strip()
        if label and label.lower() not in out.lower():
            out = f"{out} · {label}"
        return out[:160]

    family, phase, rest = _resolve_family_phase(graph, name)
    if family:
        parts = [humanize_identifier(family)]
    elif name and name.lower() not in _GENERIC_NAMES:
        parts = [humanize_identifier(name)]
    else:
        parts = [_composition_title(graph)]
    if phase:
        parts.append(str(phase))
    tail = [t for t in rest if t]
    if tail:
        parts.append(" ".join(tail))
    if label and not any(label.lower() == p.lower() for p in parts[1:]):
        if not (tail and label.lower() in " ".join(tail).lower()):
            parts.append(label)
    return " · ".join(p for p in parts if p)[:160]


def model_name_slug(*parts: str | None, max_len: int = 64) -> str:
    """Registry-safe slug (``^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$``)."""
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        text = re.sub(r"[^a-z0-9]+", "-", str(part).lower()).strip("-")
        if text:
            tokens.append(text)
    slug = "-".join(tokens) or "model"
    slug = re.sub(r"-{2,}", "-", slug).strip("-")[:max_len].strip("-")
    return slug or "model"


__all__ = [
    "graph_family_and_phase",
    "humanize_identifier",
    "ingest_label_hint",
    "model_name_slug",
    "run_display_name",
]
