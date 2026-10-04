# app/core/runs/run_summary.py
"""
Bounded Context:  BC6 — Observability & Storage (run results)
Responsibility:   Turn a finished run into user-facing results: per-path
                  metrics, the model files each path produced, the best
                  path, the dataset that was used, and the regression
                  against the best previous run of the same graph.
Owns:             run_insights() (cached summary + models + display name),
                  run_summary_fields() (``summary`` / ``regression`` /
                  ``display_name`` for run rows), run_models(),
                  compute_paths() (fork branches after the last shared node),
                  path_labels() (config diff → "DS-CNN · 30 epochs"),
                  node_labels() (node_id → "Trainer · Path C (MobileNet · lr 0.002)"),
                  model file discovery (keras / SavedModel / tflite / onnx / pt),
                  resolve_workspace_path(), to_workspace_rel().
Public Surface:   run_insights, run_summary_fields, run_models, compute_paths,
                  path_labels, node_labels, resolve_workspace_path, to_workspace_rel,
                  read_labels_txt, model_row_for_path, PRIMARY_METRICS,
                  clear_cache
Must NOT:         Import app.domain / app.api; write into run dirs or
                  artifacts (read-only); raise on malformed runs (degrade
                  to empty summaries).
Dependencies:     stdlib (json, os, re, threading, time, datetime, pathlib);
                  app.core.config; app.core.paths.workspace_paths;
                  app.core.runs.run_outputs (load_run_graph),
                  run_status, run_display, run_dataset.
Reason To Change: Metrics / model artifact conventions of evaluator,
                  trainer, model_builder or optimizer nodes change, or the
                  summary schema evolves.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUMMARY_VERSION = 1
PRIMARY_METRICS: tuple[str, ...] = ("test_accuracy", "accuracy", "val_accuracy", "f1")


def higher_is_better(name: str) -> bool:
    """Prefer higher values unless the metric name implies loss/error/latency."""
    return not re.search(r"(loss|error|mae|mse|rmse|latency|duration)", str(name or ""), re.I)
MODEL_FILE_FORMATS = {
    ".keras": "keras",
    ".h5": "keras",
    ".tflite": "tflite",
    ".onnx": "onnx",
    ".pt": "pt",
    ".pth": "pt",
}
_MODEL_REF_KEYS = (
    "model_path",
    "artifact_path",
    "keras_model_path",
    "saved_model_path",
    "tflite_path",
    "onnx_path",
    "output_model_path",
)
_OUTPUT_DIR_KEYS = ("output_path", "output_dir", "model_dir", "export_dir")
_SKIP_SUBDIRS = frozenset({"checkpoints", "variables", "assets", "__pycache__"})
_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "success", "completed", "error"})
_BUILDER_HINTS = ("model_builder", "build_model", "modelbuilder")
_OPTIMIZER_HINTS = ("optimiz", "quantiz", "convert", "compress", "export", "compile", "packag")

_CACHE: dict[str, tuple[tuple, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 2048


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
        _SIBLINGS.clear()


# ── paths ─────────────────────────────────────────────────────────────────────


def _isfile(p: Path) -> bool:
    try:
        return p.is_file()
    except OSError:
        return False


def _isdir(p: Path) -> bool:
    try:
        return p.is_dir()
    except OSError:
        return False


def _project_root() -> Path:
    from app.core.config import project_dir

    return project_dir()


def resolve_workspace_path(raw: Any) -> Path | None:
    """Map ``workspace/...`` / ``artifacts/...`` / absolute strings to a Path."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("\\", "/")
    root = _project_root()
    p = Path(text)
    if p.is_absolute():
        return p
    if text.startswith("workspace/"):
        return root / Path(*text.split("/")[1:])
    if text.startswith("artifacts/") or text.startswith("datasets/") or text.startswith("runs/"):
        return root / text
    return root / text


def to_workspace_rel(path: Path) -> str:
    """``{project}/artifacts/x`` → ``workspace/artifacts/x`` (Ship / edge_optimizer form)."""
    try:
        rel = Path(os.path.abspath(path)).relative_to(Path(os.path.abspath(_project_root())))
        return "workspace/" + rel.as_posix()
    except ValueError:
        return str(path)


def _iso_mtime(path: Path) -> str | None:
    try:
        target = path / "saved_model.pb" if _isdir(path) and _isfile(path / "saved_model.pb") else path
        return datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _size_bytes(path: Path) -> int | None:
    try:
        if _isfile(path):
            return path.stat().st_size
        total = 0
        for dirpath, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
        return total
    except OSError:
        return None


def _model_format(path: Path) -> str | None:
    try:
        if _isdir(path):
            return "saved_model" if _isfile(path / "saved_model.pb") else None
        if _isfile(path):
            return MODEL_FILE_FORMATS.get(path.suffix.lower())
    except OSError:
        return None
    return None


def read_labels_txt(path: Path) -> list[str] | None:
    """Labels from ``labels.txt`` next to (or inside) a model file/dir."""
    candidates = []
    if _isdir(path):
        candidates.append(path / "labels.txt")
    candidates.append(path.parent / "labels.txt")
    for cand in candidates:
        try:
            if _isfile(cand):
                rows = [ln.strip() for ln in cand.read_text(encoding="utf-8").splitlines()]
                rows = [r for r in rows if r]
                if rows:
                    return rows
        except OSError:
            continue
    return None


# ── run journal reads ─────────────────────────────────────────────────────────


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_graph(run_path: Path) -> dict[str, Any]:
    try:
        from app.core.runs.run_outputs import load_run_graph

        g = load_run_graph(run_path)
        return g if isinstance(g, dict) else {}
    except Exception:
        g = _read_json(run_path / "graph.json")
        return g if isinstance(g, dict) else {}


def _nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in (graph.get("nodes") or []) if isinstance(n, dict) and n.get("id")]


def _edges(graph: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    for e in graph.get("edges") or []:
        if isinstance(e, dict) and e.get("src_id") and e.get("dst_id"):
            out.append((str(e["src_id"]), str(e["dst_id"])))
    return out


def _ntype(node: dict[str, Any]) -> str:
    return str(node.get("node_type") or node.get("type") or "").replace("Isolated_", "")


def _cfg(node: dict[str, Any]) -> dict[str, Any]:
    c = node.get("config")
    return c if isinstance(c, dict) else {}


def _outputs_index(run_path: Path) -> list[dict[str, Any]]:
    data = _read_json(run_path / "outputs_index.json")
    rows = data.get("artifacts") if isinstance(data, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict)]


def _node_data(index: list[dict[str, Any]], node_id: str) -> dict[str, Any] | None:
    rows = [r for r in index if r.get("node_id") == node_id]
    rows.sort(key=lambda r: 0 if (r.get("port") in (None, "output")) else 1)
    for row in rows:
        dp = row.get("data_path")
        if not isinstance(dp, str) or not dp:
            continue
        base = resolve_workspace_path(dp)
        if base is None:
            continue
        for cand in (base / "data.json", base):
            if _isfile(cand):
                data = _read_json(cand)
                if isinstance(data, dict):
                    return data
    return None


def _logs(run_path: Path) -> list[dict[str, Any]]:
    data = _read_json(run_path / "logs.json")
    return [e for e in (data or []) if isinstance(e, dict)] if isinstance(data, list) else []


# ── topology ──────────────────────────────────────────────────────────────────


def _topo_order(graph: dict[str, Any]) -> list[str]:
    ids = [str(n["id"]) for n in _nodes(graph)]
    pos = {nid: i for i, nid in enumerate(ids)}
    indeg = {nid: 0 for nid in ids}
    out: dict[str, list[str]] = {nid: [] for nid in ids}
    for s, d in _edges(graph):
        if s in indeg and d in indeg:
            out[s].append(d)
            indeg[d] += 1
    ready = sorted([n for n, k in indeg.items() if k == 0], key=pos.get)
    order: list[str] = []
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for d in out[nid]:
            indeg[d] -= 1
            if indeg[d] == 0:
                ready.append(d)
                ready.sort(key=pos.get)
    order.extend(n for n in ids if n not in order)
    return order


def compute_paths(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Fork branches after the last shared node.

    Each sink's ancestry minus the nodes shared by every sink is one branch;
    branches that share a node are merged. One sink → one path of all nodes.
    Returns ``[{path_id, node_ids}]`` in topological order.
    """
    order = _topo_order(graph)
    if not order:
        return []
    parents: dict[str, set[str]] = {n: set() for n in order}
    children: dict[str, set[str]] = {n: set() for n in order}
    for s, d in _edges(graph):
        if s in parents and d in parents:
            parents[d].add(s)
            children[s].add(d)
    sinks = [n for n in order if not children[n]]

    def ancestry(n: str) -> set[str]:
        seen = {n}
        stack = [n]
        while stack:
            cur = stack.pop()
            for p in parents[cur]:
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        return seen

    if len(sinks) <= 1:
        return [{"path_id": "path-a", "node_ids": order}]
    sets = [ancestry(s) for s in sinks]
    shared = set.intersection(*sets)
    groups: list[set[str]] = []
    for s in sets:
        branch = s - shared
        if not branch:
            continue
        merged = [g for g in groups if g & branch]
        for g in merged:
            groups.remove(g)
            branch |= g
        groups.append(branch)
    if len(groups) <= 1:
        return [{"path_id": "path-a", "node_ids": order}]
    rank = {n: i for i, n in enumerate(order)}
    groups.sort(key=lambda g: min(rank[n] for n in g))
    out = []
    for i, g in enumerate(groups):
        out.append({"path_id": f"path-{_letter(i)}", "node_ids": sorted(g, key=rank.get)})
    return out


def _letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(97 + r) + s
    return s


# ── labels for parallel branches ──────────────────────────────────────────────

_ARCH_NAMES = {
    "ds_cnn": "DS-CNN",
    "dscnn": "DS-CNN",
    "simple_cnn": "CNN-small",
    "small_cnn": "CNN-small",
    "cnn": "CNN",
    "crnn": "CRNN",
    "tc_resnet": "TC-ResNet",
    "resnet": "ResNet",
    "mobilenet": "MobileNet",
    "mobilenet_v2": "MobileNetV2",
    "mobilenetv2": "MobileNetV2",
    "lstm": "LSTM",
    "gru": "GRU",
    "mlp": "MLP",
    "dense": "Dense",
    "transformer": "Transformer",
    "wav2vec2": "Wav2Vec2",
}
_LABEL_PRIORITY = ("architecture", "epochs", "batch_size", "learning_rate")
_LABEL_SKIP_KEYS = re.compile(r"(path|dir|file|device|backend|seed|uri|url|name)$", re.I)


def architecture_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    low = text.lower()
    if low in _ARCH_NAMES:
        return _ARCH_NAMES[low]
    parts = [p for p in re.split(r"[_\-\s]+", text) if p]
    return "-".join(p.upper() if len(p) <= 3 else p[:1].upper() + p[1:] for p in parts)


def _fmt_value(key: str, value: Any) -> str:
    if key == "architecture":
        return architecture_label(value)
    if key == "epochs":
        return f"{value} epochs"
    if key == "batch_size":
        return f"batch {value}"
    if key == "learning_rate":
        return f"lr {value:g}" if isinstance(value, (int, float)) else f"lr {value}"
    return f"{key.replace('_', ' ')} {value}"


def _model_configs(graph: dict[str, Any], node_ids: list[str]) -> dict[str, Any]:
    """Merged scalar configs of model-defining nodes (builder → trainer)."""
    by_id = {str(n["id"]): n for n in _nodes(graph)}
    merged: dict[str, Any] = {}
    for nid in node_ids:
        node = by_id.get(nid)
        if not node:
            continue
        t = _ntype(node).lower()
        cfg = _cfg(node)
        if not ("model" in t or "train" in t or "architecture" in cfg or "epochs" in cfg):
            continue
        for k, v in cfg.items():
            if isinstance(v, (str, int, float, bool)) and not _LABEL_SKIP_KEYS.search(k):
                merged.setdefault(k, v)
    return merged


def path_labels(graph: dict[str, Any], paths: list[dict[str, Any]]) -> dict[str, str]:
    """Human label per path describing what differs (max two facts)."""
    letters = {p["path_id"]: f"Path {p['path_id'].split('-', 1)[-1].upper()}" for p in paths}
    cfgs = {p["path_id"]: _model_configs(graph, p["node_ids"]) for p in paths}
    if len(paths) == 1:
        cfg = next(iter(cfgs.values()), {})
        facts = [_fmt_value(k, cfg[k]) for k in ("architecture", "epochs") if cfg.get(k) not in (None, "")]
        pid = paths[0]["path_id"]
        return {pid: " · ".join(f for f in facts if f) or letters[pid]}
    keys: list[str] = []
    all_keys = set().union(*[set(c) for c in cfgs.values()]) if cfgs else set()
    for k in list(_LABEL_PRIORITY) + sorted(all_keys - set(_LABEL_PRIORITY)):
        if k not in all_keys:
            continue
        values = {json.dumps(c.get(k), sort_keys=True, default=str) for c in cfgs.values()}
        if len(values) > 1:
            keys.append(k)
    out: dict[str, str] = {}
    for p in paths:
        cfg = cfgs[p["path_id"]]
        facts = [_fmt_value(k, cfg[k]) for k in keys if cfg.get(k) not in (None, "")][:2]
        out[p["path_id"]] = " · ".join(f for f in facts if f) or letters[p["path_id"]]
    seen: dict[str, int] = {}
    for label in out.values():
        seen[label] = seen.get(label, 0) + 1
    for pid, label in list(out.items()):
        if seen[label] > 1:
            out[pid] = letters[pid]
    return out


def _humanize_node_type(node_type: str) -> str:
    text = str(node_type or "node").replace("Isolated_", "").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else "Node"


def node_labels(graph: dict[str, Any]) -> dict[str, str]:
    """Human label per node: ``"Trainer · Path C (MobileNet · lr 0.002)"``.

    Nodes on a parallel branch get their path letter plus the branch's
    config-diff label; shared nodes (and single-path graphs) get the node
    label / humanized node type. Duplicate labels get ``(node_id)``.
    """
    nodes = _nodes(graph)
    if not nodes:
        return {}
    try:
        paths = compute_paths(graph)
        labels = path_labels(graph, paths) if paths else {}
    except Exception:
        paths, labels = [], {}
    path_of: dict[str, str] = {}
    if len(paths) > 1:
        for p in paths:
            for nid in p["node_ids"]:
                path_of.setdefault(nid, p["path_id"])
    out: dict[str, str] = {}
    for node in nodes:
        nid = str(node.get("id"))
        ntype = _ntype(node)
        raw = str(node.get("label") or "").strip()
        base = raw if raw and raw != ntype else _humanize_node_type(ntype)
        pid = path_of.get(nid)
        if pid:
            letter = f"Path {pid.split('-', 1)[-1].upper()}"
            plabel = labels.get(pid) or letter
            out[nid] = f"{base} · {letter}" if plabel == letter else f"{base} · {letter} ({plabel})"
        else:
            out[nid] = base
    counts: dict[str, int] = {}
    for label in out.values():
        counts[label] = counts.get(label, 0) + 1
    for nid, label in list(out.items()):
        if counts[label] > 1:
            out[nid] = f"{label} ({nid})"
    return out


# ── metrics + models per node ─────────────────────────────────────────────────


def _scalar_metrics(src: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    if not isinstance(src, dict):
        return out
    for k, v in src.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and v == v:  # drop NaN
            out[str(k)] = float(v) if isinstance(v, float) else v
    return out


def _node_output_dirs(node: dict[str, Any]) -> list[Path]:
    dirs: list[Path] = []
    cfg = _cfg(node)
    for key in _OUTPUT_DIR_KEYS:
        p = resolve_workspace_path(cfg.get(key))
        if p is None:
            continue
        if p.suffix and not _isdir(p):
            p = p.parent
        dirs.append(p)
    return dirs


def _node_metrics(node: dict[str, Any], data: dict[str, Any] | None) -> dict[str, float]:
    metrics: dict[str, float] = {}
    hist = (data or {}).get("history")
    if isinstance(hist, dict):
        for k in ("val_accuracy", "accuracy", "val_loss", "loss"):
            seq = hist.get(k)
            if isinstance(seq, list) and seq and isinstance(seq[-1], (int, float)):
                metrics[f"final_{k}"] = float(seq[-1])
    for d in _node_output_dirs(node):
        try:
            mfile = d / "metrics.json"
            if _isfile(mfile):
                metrics.update(_scalar_metrics(_read_json(mfile)))
        except OSError:
            continue
    if isinstance(data, dict):
        metrics.update(_scalar_metrics(data.get("metrics")))
    return metrics


def _scan_model_files(root: Path) -> list[Path]:
    found: list[Path] = []
    try:
        if not _isdir(root):
            return found
        if _isfile(root / "saved_model.pb"):
            return [root]
        for child in sorted(root.iterdir()):
            if child.name.startswith("."):
                continue
            if _isdir(child):
                if child.name in _SKIP_SUBDIRS:
                    continue
                if _isfile(child / "saved_model.pb"):
                    found.append(child)
                continue
            if child.suffix.lower() in MODEL_FILE_FORMATS:
                found.append(child)
    except OSError:
        pass
    return found


def _referenced_model_paths(data: dict[str, Any] | None) -> list[Path]:
    out: list[Path] = []
    if not isinstance(data, dict):
        return out
    for src in (data, data.get("metrics") if isinstance(data.get("metrics"), dict) else {}):
        for key in _MODEL_REF_KEYS:
            p = resolve_workspace_path(src.get(key))
            if p is not None:
                out.append(p)
    return out


def _model_kind(node_type: str, path: Path, fmt: str) -> str:
    t = node_type.lower()
    if any(h in t for h in _BUILDER_HINTS) or path.name.startswith("compiled_"):
        return "compiled_untrained"
    if any(h in t for h in _OPTIMIZER_HINTS) or fmt == "tflite":
        return "optimized"
    return "trained"


def _under(path: Path, roots: list[Path]) -> bool:
    ap = os.path.abspath(path)
    for r in roots:
        ar = os.path.abspath(r)
        if ap == ar or ap.startswith(ar.rstrip(os.sep) + os.sep):
            return True
    return False


# ── insights (cached) ─────────────────────────────────────────────────────────


def _cache_key(run_path: Path) -> tuple:
    key: list[Any] = [SUMMARY_VERSION]
    for name in ("meta.json", "outputs_index.json", "logs.json", "graph.json"):
        try:
            st = (run_path / name).stat()
            key.append((st.st_mtime_ns, st.st_size))
        except OSError:
            key.append(None)
    return tuple(key)


def _status(meta: dict[str, Any]) -> str:
    try:
        from app.core.runs.run_status import normalize_status

        return str(normalize_status(meta.get("status")))
    except Exception:
        return str(meta.get("status") or "").lower()


def run_insights(run_id: str, run_path: Path, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cached ``{display_name, summary, models, primary_metric, status}`` for one run.

    Terminal runs are immutable, so results are cached by journal file
    mtimes; live runs are recomputed (cheap) on every call.
    """
    key = _cache_key(run_path)
    with _CACHE_LOCK:
        hit = _CACHE.get(run_id)
        if hit is not None and hit[0] == key:
            return hit[1]
    if meta is None:
        m = _read_json(run_path / "meta.json")
        meta = m if isinstance(m, dict) else {}
    try:
        result = _compute_insights(run_id, run_path, meta)
    except Exception:
        result = {
            "display_name": str(meta.get("graph_name") or run_id),
            "summary": None,
            "models": [],
            "status": _status(meta),
        }
    if _status(meta) in _TERMINAL:
        with _CACHE_LOCK:
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[run_id] = (key, result)
    return result


def _dataset_block(graph: dict[str, Any], order: list[str], logs: list[dict[str, Any]]) -> dict[str, Any] | None:
    from app.core.runs.run_dataset import ingest_dataset_info, is_ingest_node_type

    by_id = {str(n["id"]): n for n in _nodes(graph)}
    ingest_id = next((nid for nid in order if is_ingest_node_type(_ntype(by_id.get(nid, {})))), None)
    if not ingest_id:
        return None
    end = None
    for e in logs:
        if e.get("type") == "node_end" and e.get("node_id") == ingest_id:
            end = e
    recorded = end.get("dataset") if isinstance(end, dict) and isinstance(end.get("dataset"), dict) else None
    count = end.get("output_count") if isinstance(end, dict) else None
    if recorded:
        info = dict(recorded)
    else:
        info = ingest_dataset_info(_cfg(by_id[ingest_id]), count if isinstance(count, int) else None) or {}
    if info.get("clip_count") is None and isinstance(count, int):
        info["clip_count"] = count
    return {
        "source_path": info.get("source_path"),
        "resolved_path": info.get("resolved_path"),
        "clip_count": info.get("clip_count"),
        "fallback_used": info.get("fallback_used"),
        "from_ingest_node": ingest_id,
    }


def _pick_primary(metric_sets: list[dict[str, float]]) -> str | None:
    for name in PRIMARY_METRICS:
        if any(name in m for m in metric_sets):
            return name
    for name in PRIMARY_METRICS:
        if any(f"final_{name}" in m for m in metric_sets):
            return f"final_{name}"
    # Generic fallback: first finite scalar across paths (stable key order).
    keys: list[str] = []
    seen: set[str] = set()
    for m in metric_sets:
        for k, v in m.items():
            if k in seen or not isinstance(v, (int, float)):
                continue
            seen.add(k)
            keys.append(k)
    keys.sort()
    return keys[0] if keys else None


def _compute_insights(run_id: str, run_path: Path, meta: dict[str, Any]) -> dict[str, Any]:
    from app.core.runs.run_display import model_name_slug, run_display_name, graph_family_and_phase

    graph = _load_graph(run_path)
    graph_name = str(meta.get("graph_name") or (graph.get("metadata") or {}).get("name") or "")
    display_name = run_display_name(graph, graph_name)
    nodes = {str(n["id"]): n for n in _nodes(graph)}
    order = _topo_order(graph)
    index = _outputs_index(run_path)
    logs = _logs(run_path)
    data_by_node = {nid: _node_data(index, nid) for nid in order}

    paths = compute_paths(graph)
    labels = path_labels(graph, paths) if paths else {}
    path_of: dict[str, str] = {}
    for p in paths:
        for nid in p["node_ids"]:
            path_of.setdefault(nid, p["path_id"])

    # metrics per path (topological merge; evaluator metrics win)
    path_metrics: dict[str, dict[str, float]] = {}
    for p in paths:
        merged: dict[str, float] = {}
        for nid in p["node_ids"]:
            node = nodes.get(nid)
            if node is None:
                continue
            merged.update(_node_metrics(node, data_by_node.get(nid)))
        path_metrics[p["path_id"]] = merged

    # models: owned by the node whose output dir contains them, else the
    # first node (topologically) whose output payload references them.
    owner: dict[str, str] = {}
    for nid in order:
        node = nodes.get(nid)
        if node is None:
            continue
        roots = _node_output_dirs(node)
        for root in roots:
            for mp in _scan_model_files(root):
                owner.setdefault(os.path.abspath(mp), nid)
        for mp in _referenced_model_paths(data_by_node.get(nid)):
            if roots and _under(mp, roots):
                owner.setdefault(os.path.abspath(mp), nid)
    for nid in order:
        for mp in _referenced_model_paths(data_by_node.get(nid)):
            owner.setdefault(os.path.abspath(mp), nid)

    family, _phase, _rest = graph_family_and_phase(graph_name)
    if not family:
        family = display_name.split(" · ")[0]
    fam_tokens = [t for t in re.split(r"[-_\s]+", family.lower()) if t and t not in {"e2e", "ml"}]

    models: list[dict[str, Any]] = []
    for abs_path, nid in owner.items():
        path = Path(abs_path)
        fmt = _model_format(path)
        if not fmt:
            continue
        node = nodes.get(nid, {})
        ntype = _ntype(node)
        pid = path_of.get(nid)
        data = data_by_node.get(nid) or {}
        lbls = read_labels_txt(path)
        labels_source = "labels.txt" if lbls else None
        if not lbls and isinstance(data.get("labels"), list) and data["labels"]:
            lbls = [str(x) for x in data["labels"]]
            labels_source = "node_output"
        if not lbls and pid:
            for other in next((p["node_ids"] for p in paths if p["path_id"] == pid), []):
                od = data_by_node.get(other) or {}
                if isinstance(od.get("labels"), list) and od["labels"]:
                    lbls = [str(x) for x in od["labels"]]
                    labels_source = f"node_output:{other}"
                    break
        display = None
        for src in (data.get("metrics"), data.get("metadata"), data):
            if isinstance(src, dict) and isinstance(src.get("display_name"), str) and src["display_name"].strip():
                display = src["display_name"].strip()
                break
        arch = _model_configs(graph, [n for n in (next((p["node_ids"] for p in paths if p["path_id"] == pid), []))]).get("architecture") if pid else None
        models.append(
            {
                "path": to_workspace_rel(path),
                "name": path.name,
                "display_name": display,
                "node_id": nid,
                "node_type": ntype,
                "path_id": pid,
                "path_label": labels.get(pid) if pid else None,
                "kind": _model_kind(ntype, path, fmt),
                "format": fmt,
                "size_bytes": _size_bytes(path),
                "created_at": _iso_mtime(path),
                "metrics": dict(path_metrics.get(pid) or {}) if pid else {},
                "labels": lbls or [],
                "labels_source": labels_source,
                "suggested_name": model_name_slug(
                    "-".join(fam_tokens),
                    re.sub(r"[^a-z0-9]", "", architecture_label(arch).lower()) if arch else (labels.get(pid) if pid and len(paths) > 1 else None),
                ),
            }
        )
    rank = {n: i for i, n in enumerate(order)}
    kind_rank = {"trained": 0, "optimized": 1, "compiled_untrained": 2}
    fmt_rank = {"keras": 0, "saved_model": 1, "tflite": 2, "onnx": 3, "pt": 4}
    models.sort(key=lambda m: (m["path_id"] or "", rank.get(m["node_id"], 999), kind_rank.get(m["kind"], 9), fmt_rank.get(m["format"], 9), m["path"]))
    _dedupe_suggested_names(models, paths)

    primary_name = _pick_primary(list(path_metrics.values()))
    path_rows = []
    for p in paths:
        pm = path_metrics.get(p["path_id"]) or {}
        pmodels = [m for m in models if m["path_id"] == p["path_id"]]
        if not pm and not pmodels and len(paths) > 1:
            continue
        path_rows.append(
            {
                "path_id": p["path_id"],
                "label": labels.get(p["path_id"]) or p["path_id"],
                "node_ids": p["node_ids"],
                "metrics": pm,
                "model_artifacts": pmodels,
            }
        )
    if not any(r["metrics"] or r["model_artifacts"] for r in path_rows):
        path_rows = []
    best_path_id = None
    best_value = None
    prefer_high = higher_is_better(primary_name or "")
    if primary_name:
        for r in path_rows:
            v = r["metrics"].get(primary_name)
            if not isinstance(v, (int, float)):
                continue
            if best_value is None or (prefer_high and v > best_value) or (not prefer_high and v < best_value):
                best_value, best_path_id = v, r["path_id"]
    if best_path_id is None and len(path_rows) == 1:
        best_path_id = path_rows[0]["path_id"]
    summary = {
        "primary_metric": (
            {"name": primary_name, "value": best_value} if primary_name and best_value is not None else None
        ),
        "paths": path_rows,
        "best_path_id": best_path_id,
        "dataset": _dataset_block(graph, order, logs),
    }
    return {
        "display_name": display_name,
        "summary": summary,
        "models": models,
        "status": _status(meta),
    }


def _dedupe_suggested_names(models: list[dict[str, Any]], paths: list[dict[str, Any]]) -> None:
    """One suggestion per path; distinct across paths (suffix path letter)."""
    by_path: dict[str | None, str] = {}
    for m in models:
        by_path.setdefault(m["path_id"], m["suggested_name"])
    used: dict[str, str | None] = {}
    for pid, name in list(by_path.items()):
        if name in used and used[name] != pid:
            suffix = (pid or "x").split("-", 1)[-1]
            by_path[pid] = f"{name[:60]}-{suffix}"
        used[by_path[pid]] = pid
    for m in models:
        m["suggested_name"] = by_path.get(m["path_id"], m["suggested_name"])


def run_models(run_id: str, run_path: Path, meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return list(run_insights(run_id, run_path, meta).get("models") or [])


def model_row_for_path(run_id: str, run_path: Path, raw_path: str) -> dict[str, Any] | None:
    """Return the run model row whose path matches *raw_path* (any form)."""
    target = resolve_workspace_path(raw_path)
    if target is None:
        return None
    ta = os.path.abspath(target)
    for m in run_models(run_id, run_path):
        mp = resolve_workspace_path(m.get("path"))
        if mp is not None and os.path.abspath(mp) == ta:
            return m
    return None


# ── regression vs previous runs ───────────────────────────────────────────────

_SIBLINGS: dict[str, tuple[float, tuple, list[dict[str, Any]]]] = {}
_SIBLING_TTL_S = 10.0


def _sibling_rows(runs_root: Path) -> list[dict[str, Any]]:
    """[{run_id, path, project, graph_name, created_at, status}] (short TTL cache)."""
    key = str(runs_root)
    try:
        st = runs_root.stat()
        stamp = (st.st_mtime_ns,)
    except OSError:
        return []
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _SIBLINGS.get(key)
        if hit and hit[1] == stamp and now - hit[0] < _SIBLING_TTL_S:
            return hit[2]
    rows: list[dict[str, Any]] = []
    try:
        entries = list(runs_root.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        if not _isdir(entry):
            continue
        meta = _read_json(entry / "meta.json")
        if not isinstance(meta, dict):
            continue
        rows.append(
            {
                "run_id": str(meta.get("run_id") or entry.name),
                "path": entry,
                "meta": meta,
                "project": meta.get("project"),
                "graph_name": meta.get("graph_name"),
                "created_at": str(meta.get("created_at") or ""),
                "status": _status(meta),
            }
        )
    with _CACHE_LOCK:
        _SIBLINGS[key] = (now, stamp, rows)
    return rows


def compute_regression(
    run_id: str,
    meta: dict[str, Any],
    primary: dict[str, Any] | None,
    runs_root: Path | None = None,
) -> dict[str, Any] | None:
    """Compare *primary* with the best previous succeeded run (same graph+project)."""
    if not isinstance(primary, dict) or not isinstance(primary.get("value"), (int, float)):
        return None
    graph_name = meta.get("graph_name")
    if not graph_name:
        return None
    if runs_root is None:
        from app.core.config import runs_dir

        runs_root = runs_dir()
    created = str(meta.get("created_at") or "")
    best_id = None
    best_val = None
    for row in _sibling_rows(runs_root):
        if row["run_id"] == run_id or row["status"] not in ("succeeded", "success"):
            continue
        if row["graph_name"] != graph_name or (row["project"] or None) != (meta.get("project") or None):
            continue
        if created and row["created_at"] and row["created_at"] >= created:
            continue
        ins = run_insights(row["run_id"], row["path"], row["meta"])
        pm = ((ins.get("summary") or {}).get("primary_metric") or {})
        if pm.get("name") != primary.get("name") or not isinstance(pm.get("value"), (int, float)):
            continue
        prefer_high = higher_is_better(str(primary.get("name") or ""))
        if best_val is None or (prefer_high and pm["value"] > best_val) or (not prefer_high and pm["value"] < best_val):
            best_val, best_id = pm["value"], row["run_id"]
    if best_id is None:
        return None
    return {
        "metric": primary.get("name"),
        "best_previous_run_id": best_id,
        "best_previous_value": best_val,
        "delta": float(primary["value"]) - float(best_val),
    }


def run_summary_fields(
    run_id: str,
    run_path: Path,
    meta: dict[str, Any],
    *,
    include_regression: bool = True,
) -> dict[str, Any]:
    """``{display_name, summary, regression}`` to merge into a run row.

    List endpoints should pass ``include_regression=False`` — sibling scans
    re-enter ``run_insights`` and dominate list latency on large workspaces.
    """
    ins = run_insights(run_id, run_path, meta)
    summary = ins.get("summary")
    primary = (summary or {}).get("primary_metric") if isinstance(summary, dict) else None
    regression = None
    if include_regression:
        try:
            regression = compute_regression(run_id, meta, primary, runs_root=run_path.parent)
        except Exception:
            regression = None
    return {
        "display_name": ins.get("display_name"),
        "summary": summary,
        "regression": regression,
    }


__all__ = [
    "MODEL_FILE_FORMATS",
    "PRIMARY_METRICS",
    "architecture_label",
    "clear_cache",
    "higher_is_better",
    "compute_paths",
    "compute_regression",
    "model_row_for_path",
    "node_labels",
    "path_labels",
    "read_labels_txt",
    "resolve_workspace_path",
    "run_insights",
    "run_models",
    "run_summary_fields",
    "to_workspace_rel",
]
