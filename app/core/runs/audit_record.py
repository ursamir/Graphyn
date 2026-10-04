# app/core/runs/audit_record.py
"""
Bounded Context:  BC6 — Observability (Prove pillar / run audit record)
Responsibility:   Capture everything needed to trace and reproduce a run —
                  node implementations (plugin name / version / code hash),
                  environment, external inputs (content hashes + dataset
                  version), saved-pipeline revision, cache provenance,
                  per-node output manifests — seal it into a hash-chained,
                  tamper-evident record, and verify a sealed run later.
Owns:             capture_run_start(), seal_run_record(), verify_run(),
                  check_external_inputs(), pipeline_drift(),
                  node_implementations(), capture_environment(),
                  collect_external_inputs(), resolve_pipeline_ref(),
                  record_hash(), the per-project chain files
                  ``{project}/audit/chains/<project>.jsonl`` and the
                  ``runs/<id>/graph.logical.json`` / ``outputs_manifest.json``
                  sidecars.
Public Surface:   capture_run_start, seal_run_record, verify_run,
                  check_external_inputs, pipeline_drift, record_hash,
                  chain_path, load_record, logical_graph_for_run,
                  RECORD_SCHEMA_VERSION
Must NOT:         Import app.api, orchestrator or app.domain; raise into run
                  lifecycle callers (capture/seal are best-effort).
Dependencies:     stdlib; app.core.runs.audit_hashing; app.core.config;
                  app.core.nodes registry / plugins runtime registry / store,
                  app.core.pipelines (lazy); app.core.paths.workspace_paths (lazy).
Reason To Change: Audit record schema, chain format or verify checks change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import socket
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.core.runs.audit_hashing import hash_file, hash_path, tree_listing

log = logging.getLogger(__name__)

RECORD_SCHEMA_VERSION = "2.0"
LOGICAL_GRAPH_FILE = "graph.logical.json"
OUTPUTS_MANIFEST_FILE = "outputs_manifest.json"
_MANIFEST_FILES_PER_ROOT = 5000

# Config keys that are write sinks (never external inputs).
_WRITE_KEYS = frozenset({
    "output_path", "output_dir", "export_dir", "dest_dir", "checkpoint_path",
    "save_path", "log_dir", "cache_dir", "out_dir", "output_file", "report_path",
})
# Keys that are inputs even when the path does not exist (recorded as missing).
_INPUT_KEYS = frozenset({
    "path", "model_path", "manifest_path", "input_path", "data_path", "dataset_path",
    "labels_path", "input_dir", "data_dir", "source_path", "audio_path", "file_path",
    "weights_path", "vocab_path", "config_path", "resume_from", "representative_data_path",
})
_PATHISH_RE = re.compile(r"^(?:/|workspace/|datasets/|artifacts/|examples/|\./)|\.[A-Za-z0-9]{1,6}$")
_LIBS = (
    "numpy", "scipy", "pandas", "scikit-learn", "librosa", "soundfile", "tensorflow",
    "tensorflow-cpu", "keras", "torch", "torchaudio", "onnx", "onnxruntime", "tflite-runtime",
    "pydantic", "fastapi",
)

_chain_lock = threading.Lock()
_env_cache: dict[str, Any] | None = None
_plugin_hash_cache: dict[str, tuple[str, str]] = {}


# ── helpers ──────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def record_hash(record: dict[str, Any]) -> str:
    """sha256 of the canonical record content without ``record_hash``."""
    body = {k: v for k, v in record.items() if k != "record_hash"}
    return hashlib.sha256(_canonical(body)).hexdigest()


def graph_content_hash(graph: dict[str, Any]) -> str:
    """Same formula as RunManager.save_graph_ir / orchestrator logical hash."""
    return hashlib.sha256(json.dumps(graph, sort_keys=True, default=str).encode()).hexdigest()


def _semantic_hash(graph: dict[str, Any]) -> str:
    body = {k: v for k, v in graph.items() if k != "ui"}
    return graph_content_hash(body)


def _project_root() -> Path:
    from app.core.config import project_dir

    return project_dir()


def resolve_path(raw: str) -> Path:
    text = raw.strip().replace("\\", "/")
    p = Path(text)
    if p.is_absolute():
        return p
    root = _project_root()
    if text.startswith("workspace/"):
        return root / Path(*text.split("/")[1:])
    return root / text


def to_rel(path: Path) -> str:
    try:
        rel = os.path.relpath(path, _project_root())
        if not rel.startswith(".."):
            return "workspace/" + Path(rel).as_posix()
    except ValueError:
        pass
    return path.as_posix()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


# ── environment ──────────────────────────────────────────────────────────────


def _dist_version(name: str) -> str | None:
    try:
        from importlib import metadata

        return metadata.version(name)
    except Exception:
        return None


def _git_commit() -> str | None:
    env = (os.environ.get("GRAPHYN_GIT_SHA") or "").strip()
    if env:
        return env
    here = Path(__file__).resolve()
    for parent in list(here.parents)[:6]:
        git = parent / ".git"
        if git.is_file():  # worktree: "gitdir: <path>"
            try:
                text = git.read_text(encoding="utf-8").strip()
                if text.startswith("gitdir:"):
                    git = Path(text.split(":", 1)[1].strip())
            except OSError:
                return None
        if not git.is_dir():
            continue
        try:
            head = (git / "HEAD").read_text(encoding="utf-8").strip()
            if not head.startswith("ref:"):
                return head or None
            ref = head.split(":", 1)[1].strip()
            ref_file = git / ref
            if ref_file.is_file():
                return ref_file.read_text(encoding="utf-8").strip() or None
            common = git
            cd = git / "commondir"
            if cd.is_file():
                common = (git / cd.read_text(encoding="utf-8").strip()).resolve()
                if (common / ref).is_file():
                    return (common / ref).read_text(encoding="utf-8").strip() or None
            packed = common / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    parts = line.strip().split(" ")
                    if len(parts) == 2 and parts[1] == ref:
                        return parts[0]
        except OSError:
            return None
        return None
    return None


def _container_info() -> tuple[str | None, str | None]:
    digest = (os.environ.get("GRAPHYN_IMAGE_DIGEST") or "").strip() or None
    cid = None
    for path in ("/proc/self/cgroup", "/proc/self/mountinfo"):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = re.search(r"(?:docker|containers|cri-containerd)[-/]([0-9a-f]{64})", text)
        if m:
            cid = m.group(1)
            break
    return digest, cid


def capture_environment(*, refresh: bool = False) -> dict[str, Any]:
    """Python / OS / key library versions / image digest / git commit (cached)."""
    global _env_cache
    if _env_cache is not None and not refresh:
        return dict(_env_cache)
    libs: dict[str, str | None] = {}
    for name in _LIBS:
        ver = _dist_version(name)
        if ver is not None or name in ("numpy", "tensorflow", "keras", "librosa", "torch", "onnx"):
            libs[name] = ver
    digest, cid = _container_info()
    try:
        from app import __version__ as gv
    except Exception:
        gv = "unknown"
    env = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": sys.executable,
        "os": platform.platform(),
        "machine": platform.machine(),
        "hostname": socket.gethostname(),
        "libraries": libs,
        "container_image_digest": digest,
        "container_id": cid,
        "git_commit": _git_commit(),
        "graphyn_version": _dist_version("graphyn-sdk") or gv,
        "backend": (os.environ.get("GRAPHYN_BACKEND") or "local_python").strip() or "local_python",
    }
    _env_cache = env
    return dict(env)


def _venv_libraries(venv_python: str) -> dict[str, str]:
    """Key library versions inside an isolated plugin venv (dist-info scan)."""
    out: dict[str, str] = {}
    try:
        root = Path(venv_python).resolve().parent.parent
        wanted = {n.replace("-", "_").lower() for n in _LIBS}
        for sp in root.glob("lib/python*/site-packages"):
            for info in sp.glob("*.dist-info"):
                stem = info.name[: -len(".dist-info")]
                if "-" not in stem:
                    continue
                name, ver = stem.rsplit("-", 1)
                if name.replace("-", "_").lower() in wanted:
                    out[name.lower().replace("_", "-")] = ver
    except Exception:
        pass
    return out


# ── node implementations ─────────────────────────────────────────────────────


def _find_plugin_dir(start: Path) -> Path | None:
    cur = start if start.is_dir() else start.parent
    for _ in range(4):
        if (cur / "plugin.toml").is_file() or (cur / "plugin.json").is_file():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _read_manifest(plugin_dir: Path) -> dict[str, Any]:
    toml_p = plugin_dir / "plugin.toml"
    if toml_p.is_file():
        try:
            import tomllib

            data = tomllib.loads(toml_p.read_text(encoding="utf-8"))
            return dict(data.get("plugin") or data)
        except Exception:
            return {}
    data = _read_json(plugin_dir / "plugin.json")
    return data if isinstance(data, dict) else {}


def plugin_code_hash(plugin_dir: str | Path) -> str | None:
    """sha256 over the plugin's source tree (cached by tree stat signature)."""
    res = hash_path(plugin_dir, max_bytes=1 << 62, max_files=1 << 30)
    return res.get("content_hash")


def _node_impl(node_type: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "plugin": None, "version": None, "runtime": "builtin",
        "plugin_code_hash": None, "node_version": None, "source": None,
    }
    cls = None
    try:
        from app.core.nodes import registry

        try:
            info["node_version"] = str(registry.get_metadata(node_type).version)
        except Exception:
            pass
        try:
            cls = registry.get_class(node_type)
        except Exception:
            cls = None
    except Exception:
        pass
    plugin_dir: Path | None = None
    plugin_name: str | None = None
    try:
        from app.core.plugins.runtime_registry import get_runtime_registry

        spec = get_runtime_registry().get_for_node(node_type)
    except Exception:
        spec = None
    if spec is not None:
        plugin_dir = Path(spec.install_path)
        plugin_name = spec.plugin_name
        info["runtime"] = "isolated"
        libs = _venv_libraries(spec.venv_python)
        if libs:
            info["venv_libraries"] = libs
    elif cls is not None:
        try:
            import inspect

            src = inspect.getsourcefile(cls)
        except Exception:
            src = None
        if src:
            plugin_dir = _find_plugin_dir(Path(src))
            if plugin_dir is None:
                info["module"] = getattr(cls, "__module__", None)
                try:
                    info["plugin_code_hash"] = "sha256:" + hash_file(src)
                    info["source"] = to_rel(Path(src)) if not str(src).startswith(str(Path(__file__).resolve().parents[2])) else os.path.relpath(src, Path(__file__).resolve().parents[3])
                except OSError:
                    pass
            else:
                info["runtime"] = "inprocess"
    if plugin_dir is not None:
        manifest = _read_manifest(plugin_dir)
        plugin_name = plugin_name or manifest.get("name") or plugin_dir.name
        info["plugin"] = plugin_name
        info["version"] = str(manifest.get("version")) if manifest.get("version") else None
        try:
            from app.core.plugins.store import PluginStore

            rec = PluginStore().get(str(plugin_name))
            if rec is not None and getattr(rec, "version", None):
                info["version"] = str(rec.version)
                info["installed_from"] = str(getattr(rec, "source", "") or "") or None
        except Exception:
            pass
        info["source"] = str(plugin_dir)
        info["plugin_code_hash"] = plugin_code_hash(plugin_dir)
    if info["version"] is None:
        info["version"] = info["node_version"] or "builtin"
    return info


def node_implementations(node_types: Iterable[str]) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    """Return ``(node_type → impl, plugin → version, plugin → code hash)``."""
    impls: dict[str, Any] = {}
    versions: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for nt in node_types:
        if not nt or nt in impls:
            continue
        try:
            impl = _node_impl(str(nt))
        except Exception as exc:  # never fatal
            impl = {"plugin": None, "version": "unknown", "runtime": "unknown", "error": str(exc)}
        impls[str(nt)] = impl
        if impl.get("plugin"):
            versions[str(impl["plugin"])] = str(impl.get("version") or "")
            if impl.get("plugin_code_hash"):
                hashes[str(impl["plugin"])] = str(impl["plugin_code_hash"])
    return impls, versions, hashes


# ── external inputs ──────────────────────────────────────────────────────────


def _graph_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in (graph.get("nodes") or []) if isinstance(n, dict)]


def _node_type(node: dict[str, Any]) -> str:
    return str(node.get("node_type") or node.get("type") or "")


def _walk_config(cfg: Any, key: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(cfg, str):
        yield key, cfg
    elif isinstance(cfg, dict):
        for k, v in cfg.items():
            yield from _walk_config(v, str(k))
    elif isinstance(cfg, list):
        for item in cfg:
            yield from _walk_config(item, key)


def _dataset_version(path: Path) -> dict[str, str] | None:
    try:
        from app.core.config import datasets_output_dir

        root = datasets_output_dir().resolve()
        rel = path.resolve().relative_to(root)
    except Exception:
        return None
    parts = rel.parts
    if len(parts) >= 2 and re.fullmatch(r"v\d+", parts[1]):
        return {"project": parts[0], "version": parts[1]}
    return None


def _run_scoped(raw: str, run_id: str) -> bool:
    return f"/runs/{run_id}" in "/" + raw.replace("\\", "/")


def collect_external_inputs(graph: dict[str, Any], run_id: str = "") -> list[dict[str, Any]]:
    """Every external path a node reads (config path strings), hashed."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for node in _graph_nodes(graph):
        nid = str(node.get("id") or "")
        ntype = _node_type(node)
        for key, raw in _walk_config(node.get("config") or {}):
            if not raw or not raw.strip() or key in _WRITE_KEYS or "://" in raw:
                continue
            text = raw.strip()
            if len(text) > 1024 or "\n" in text:
                continue
            if run_id and _run_scoped(text, run_id):
                continue  # produced by this run
            known = key in _INPUT_KEYS or key.endswith(("_path", "_dir", "_file"))
            if not known and not _PATHISH_RE.search(text):
                continue
            if not known and "/" not in text:
                continue
            path = resolve_path(text)
            if ntype == "dataset_ingest" and key == "path":
                try:
                    from app.core.paths.workspace_paths import resolve_ingest_dir

                    path = resolve_ingest_dir(text)
                except Exception:
                    pass
            exists = path.exists()
            if not exists and not known:
                continue
            if (nid, text) in seen:
                continue
            seen.add((nid, text))
            res = hash_path(path)
            entry = {
                "node_id": nid,
                "node_type": ntype,
                "key": key,
                "path": text,
                "resolved": to_rel(path),
                **res,
                "dataset": _dataset_version(path) if exists else None,
            }
            out.append(entry)
    return out


def dataset_versions_from_inputs(inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in inputs:
        ds = e.get("dataset")
        if isinstance(ds, dict):
            out.append({**ds, "path": e.get("path"), "content_hash": e.get("content_hash"), "node_id": e.get("node_id")})
    return out


def check_external_inputs(recorded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-hash recorded external inputs; return one result row per input."""
    rows: list[dict[str, Any]] = []
    for e in recorded or []:
        if not isinstance(e, dict) or not e.get("path"):
            continue
        resolved = e.get("resolved") or e.get("path")
        path = resolve_path(str(resolved))
        mode = e.get("hash_mode")
        if mode == "manifest":
            cur = hash_path(path, max_bytes=-1, max_files=-1)
        else:
            cur = hash_path(path, max_bytes=1 << 62, max_files=1 << 30)
        expected = e.get("content_hash")
        actual = cur.get("content_hash")
        if cur.get("kind") == "missing":
            status = "pass" if e.get("kind") == "missing" else "missing"
        elif expected and actual == expected:
            status = "pass"
        else:
            status = "changed"
        rows.append({
            "check": "external_input",
            "target": e.get("path"),
            "node_id": e.get("node_id"),
            "status": status,
            "expected": expected,
            "actual": actual,
            "details": {"file_count": cur.get("file_count"), "recorded_file_count": e.get("file_count"),
                        "hash_mode": mode},
        })
    return rows


# ── outputs ──────────────────────────────────────────────────────────────────


def output_roots(graph: dict[str, Any]) -> list[tuple[str, str]]:
    """``(node_id, posix path)`` write roots under ``workspace/artifacts``."""
    roots: list[tuple[str, str]] = []
    seen: set[str] = set()
    for node in _graph_nodes(graph):
        nid = str(node.get("id") or "")
        cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
        for key in ("output_path", "output_dir", "export_dir", "dest_dir"):
            raw = cfg.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            posix = raw.strip().replace("\\", "/").rstrip("/")
            if "artifacts/" not in posix or posix in seen:
                continue
            seen.add(posix)
            roots.append((nid, posix))
    return roots


def _output_manifests(graph: dict[str, Any], run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sidecar: dict[str, Any] = {}
    for nid, posix in output_roots(graph):
        path = resolve_path(posix)
        res = hash_path(path)
        if res.get("kind") == "missing":
            continue
        rows.append({"node_id": nid, "path": posix, **res})
        if res.get("hash_mode") == "content":
            try:
                listing = tree_listing(path, limit=_MANIFEST_FILES_PER_ROOT)
                sidecar[posix] = {rel: [size, sha] for rel, size, sha in listing}
            except OSError:
                pass
    return rows, sidecar


# ── saved pipeline revision ──────────────────────────────────────────────────


def _prepared_hash(graph_data: dict[str, Any], project: str | None) -> tuple[str, str] | None:
    """(logical hash, semantic hash) of a saved graph prepared like a run."""
    try:
        from app.core.ir.loader import dump_ir, load_ir
        from app.core.paths.workspace_paths import apply_output_rewire

        clean = {k: v for k, v in graph_data.items() if not str(k).startswith("_")}
        g = apply_output_rewire(load_ir(clean))
        if project:
            from app.core.execution.graph_prepare import stamp_graph_project

            g, _ = stamp_graph_project(g, {"project": project})
        dumped = dump_ir(g)
        return graph_content_hash(dumped), _semantic_hash(dumped)
    except Exception:
        log.debug("prepared hash failed", exc_info=True)
        return None


def _project_pipelines_dir(project: str) -> Path | None:
    try:
        from app.core.config import datasets_output_dir

        pdir = datasets_output_dir() / project
        return pdir if (pdir / "pipelines").is_dir() else None
    except Exception:
        return None


def _revisions(pdir: Path, name: str) -> list[dict[str, Any]]:
    """Draft head + published versions of one saved pipeline."""
    from app.core.pipelines.pipeline_environments import get_environments, get_version, list_versions
    from app.core.pipelines.project_pipelines import get_pipeline

    revs: list[dict[str, Any]] = []
    try:
        envs = get_environments(pdir, name)
    except Exception:
        envs = {}
    env_of: dict[str, str] = {}
    for env_name in ("prod", "staging"):
        vid = envs.get(env_name) if isinstance(envs, dict) else None
        if vid and vid not in env_of:
            env_of[str(vid)] = env_name
    try:
        revs.append({"env": "draft", "version": None, "graph": get_pipeline(pdir, name)})
    except Exception:
        pass
    try:
        for row in list_versions(pdir, name)[:50]:
            vid = row.get("version")
            try:
                revs.append({"env": env_of.get(str(vid)), "version": vid, "graph": get_version(pdir, name, str(vid))})
            except Exception:
                continue
    except Exception:
        pass
    return revs


def _strip_graph_payload(graph: Any) -> dict[str, Any]:
    if isinstance(graph, dict) and isinstance(graph.get("graph"), dict) and "schema_version" not in graph:
        graph = graph["graph"]
    if isinstance(graph, dict):
        return {k: v for k, v in graph.items() if k not in ("resource_version",)}
    return {}


def _ref(project: str, name: str, env: str | None, version: str | None, rev_hash: str | None, match: str) -> dict[str, Any]:
    label = f"{name}@{version}" if version else f"{name}@draft:{(rev_hash or '')[:12]}"
    return {"project": project, "name": name, "env": env, "version": version,
            "revision_hash": rev_hash, "match": match, "label": label}


def resolve_pipeline_ref(meta: dict[str, Any], graph: dict[str, Any], graph_hash: str) -> tuple[dict[str, Any] | None, str]:
    """Return ``(pipeline_version ref | None, pipeline_source)``."""
    gmeta = graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {}
    project = str(meta.get("project") or gmeta.get("project") or "").strip()
    declared = str(meta.get("pipeline_name") or "").strip()
    declared_env = str(meta.get("pipeline_env") or "").strip().lower() or None
    declared_version = str(meta.get("pipeline_version_id") or "").strip() or None
    if not project:
        return None, "adhoc"
    pdir = _project_pipelines_dir(project)
    if pdir is None:
        return None, "adhoc"
    names: list[str] = []
    if declared:
        names.append(declared)
    gname = str(gmeta.get("name") or "").strip()
    if gname and gname not in names:
        names.append(gname)
    try:
        from app.core.pipelines.project_pipelines import list_pipelines

        for row in list_pipelines(pdir)[:50]:
            n = str(row.get("name") or "")
            if n and n not in names:
                names.append(n)
    except Exception:
        pass
    existing: set[str] = set()
    for name in names:
        revs = _revisions(pdir, name)
        if revs:
            existing.add(name)
        for rev in revs:
            hashed = _prepared_hash(_strip_graph_payload(rev["graph"]), project)
            if hashed and hashed[0] == graph_hash:
                env = declared_env if (declared and name == declared and declared_env) else rev["env"]
                return _ref(project, name, env, rev["version"], hashed[0],
                            "declared" if declared == name else "content_hash"), "saved"
    if declared and declared in existing:
        rev_hash = None
        try:
            from app.core.pipelines.pipeline_environments import get_environment_graph

            g = get_environment_graph(pdir, declared, declared_env or "draft")
            hashed = _prepared_hash(_strip_graph_payload(g), project)
            rev_hash = hashed[0] if hashed else None
        except Exception:
            pass
        return _ref(project, declared, declared_env or "draft", declared_version, rev_hash, "declared"), "saved_modified"
    if gname and gname in existing:
        return _ref(project, gname, "draft", None, None, "name_only"), "saved_modified"
    return None, "adhoc"


def pipeline_drift(ref: dict[str, Any] | None, run_graph_hash: str, run_semantic_hash: str | None) -> dict[str, Any] | None:
    """Compare the run's graph with the CURRENT saved pipeline (same name/env)."""
    if not isinstance(ref, dict) or not ref.get("project") or not ref.get("name"):
        return None
    project, name = str(ref["project"]), str(ref["name"])
    env = str(ref.get("env") or "draft")
    out: dict[str, Any] = {
        "project": project, "pipeline": name, "env": env,
        "run_graph_hash": run_graph_hash, "current_hash": None,
        "drifted": None, "layout_only": False, "checked_at": _now(),
    }
    pdir = _project_pipelines_dir(project)
    if pdir is None:
        return out
    try:
        from app.core.pipelines.pipeline_environments import get_environment_graph

        g = get_environment_graph(pdir, name, env)
    except Exception:
        return out
    hashed = _prepared_hash(_strip_graph_payload(g), project)
    if not hashed:
        return out
    out["current_hash"] = hashed[0]
    out["drifted"] = hashed[0] != run_graph_hash
    if out["drifted"] and run_semantic_hash and hashed[1] == run_semantic_hash:
        out["layout_only"] = True
    return out


# ── logical graph sidecar ────────────────────────────────────────────────────


def write_logical_graph(run_dir: str | Path, graph: dict[str, Any]) -> None:
    path = Path(run_dir) / LOGICAL_GRAPH_FILE
    try:
        _atomic_write_json(path, graph)
    except Exception:
        log.debug("could not write %s", path, exc_info=True)


def descope_graph(graph: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Undo ``runs/<run_id>/`` scoping (legacy runs without graph.logical.json)."""
    rid = re.escape(str(run_id))
    pat = re.compile(rf"(artifacts/[^/\s]+)/runs/{rid}(?=/|$)")

    def fix(v: Any) -> Any:
        if isinstance(v, str):
            return pat.sub(r"\1", v)
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        if isinstance(v, list):
            return [fix(x) for x in v]
        return v

    return fix(graph)


def logical_graph_for_run(run_dir: str | Path) -> dict[str, Any] | None:
    """The run's logical (pre-scoping) graph: sidecar, else de-scoped graph.json."""
    run_dir = Path(run_dir)
    data = _read_json(run_dir / LOGICAL_GRAPH_FILE)
    if isinstance(data, dict):
        return data
    mat = _read_json(run_dir / "graph.json")
    if isinstance(mat, dict):
        return descope_graph(mat, run_dir.name)
    return None


# ── run start capture ────────────────────────────────────────────────────────


def capture_run_start(run: Any, logical_graph: dict[str, Any], materialized_graph: dict[str, Any], graph_hash: str) -> dict[str, Any]:
    """Persist start-time audit facts into meta.json (best-effort, never raises).

    Returns ``{"node_labels": {...}}`` for the caller's logger.
    """
    captured: dict[str, Any] = {"node_labels": {}}
    try:
        from app.core.runs.run_summary import node_labels

        captured["node_labels"] = node_labels(materialized_graph)
    except Exception:
        log.debug("node label capture failed", exc_info=True)
    writer = getattr(run, "_write_meta_field", None)
    base = getattr(run, "base_path", None)
    run_id = str(getattr(run, "run_id", "") or "")
    if not callable(writer):
        return captured
    if base:
        write_logical_graph(base, logical_graph)

    def _w(key: str, value: Any) -> None:
        try:
            writer(key, value)
        except Exception:
            log.debug("meta write %s failed", key, exc_info=True)

    try:
        impls, versions, hashes = node_implementations(_node_type(n) for n in _graph_nodes(materialized_graph))
        _w("node_implementations", impls)
        _w("plugin_version", versions)
        _w("plugin_code_hashes", hashes)
    except Exception:
        log.debug("node implementation capture failed", exc_info=True)
    try:
        _w("environment_info", capture_environment())
    except Exception:
        log.debug("environment capture failed", exc_info=True)
    try:
        inputs = collect_external_inputs(materialized_graph, run_id)
        _w("external_inputs", inputs)
        _w("dataset_versions", dataset_versions_from_inputs(inputs))
    except Exception:
        log.debug("external input capture failed", exc_info=True)
    try:
        meta = {}
        if base:
            meta = _read_json(Path(base) / "meta.json") or {}
        ref, source = resolve_pipeline_ref(meta if isinstance(meta, dict) else {}, logical_graph, graph_hash)
        _w("pipeline_ref", ref)
        _w("pipeline_source", source)
    except Exception:
        log.debug("pipeline ref capture failed", exc_info=True)
    _w("node_labels", captured["node_labels"])
    return captured


# ── chain ────────────────────────────────────────────────────────────────────


def _chain_name(project: str | None) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(project or "").strip()).strip("-.")
    return name or "_global"


def chain_path(project: str | None) -> Path:
    from app.core.trust.audit import audit_dir

    return audit_dir() / "chains" / f"{_chain_name(project)}.jsonl"


def read_chain(project: str | None) -> list[dict[str, Any]]:
    path = chain_path(project)
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")
        try:
            import fcntl

            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        try:
            import fcntl

            fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        self.fh.close()


# ── sealing ──────────────────────────────────────────────────────────────────


def _cache_rows(meta: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for s in meta.get("node_stats") or []:
        if isinstance(s, dict) and s.get("cache_hit"):
            rows.append({"node_id": s.get("node_id"), "node_type": s.get("node_type"),
                         "cache_key": s.get("cache_key"), "source_run_id": s.get("cache_source_run_id")})
    return rows


def _input_artifact_hashes(meta: dict[str, Any], artifacts: list[Any] | None) -> list[str]:
    if isinstance(meta.get("input_artifact_hashes"), list):
        return [str(x) for x in meta["input_artifact_hashes"]]
    out: list[str] = []
    for a in artifacts or []:
        h = getattr(a, "content_hash", None) if not isinstance(a, dict) else a.get("content_hash")
        if h:
            out.append(str(h))
    return out


def build_record(
    run_dir: Path,
    *,
    run_id: str,
    status: str,
    meta: dict[str, Any],
    graph: dict[str, Any] | None,
    artifacts: list[Any] | None = None,
    include_outputs: bool = True,
) -> dict[str, Any]:
    graph = graph or {}
    gmeta = graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {}
    seed_raw = gmeta.get("seed", meta.get("seed"))
    try:
        seed = int(seed_raw) if seed_raw is not None else None
    except (TypeError, ValueError):
        seed = None
    node_types = [_node_type(n) for n in _graph_nodes(graph)]
    impls = meta.get("node_implementations")
    versions = meta.get("plugin_version")
    hashes = meta.get("plugin_code_hashes")
    if not isinstance(impls, dict) or not impls:
        impls, versions, hashes = node_implementations(node_types)
    env_info = meta.get("environment_info") if isinstance(meta.get("environment_info"), dict) else capture_environment()
    inputs = meta.get("external_inputs")
    if not isinstance(inputs, list):
        inputs = collect_external_inputs(graph, run_id)
    ds_versions = meta.get("dataset_versions") if isinstance(meta.get("dataset_versions"), list) else dataset_versions_from_inputs(inputs)
    labels = meta.get("node_labels")
    if not isinstance(labels, dict):
        try:
            from app.core.runs.run_summary import node_labels

            labels = node_labels(graph)
        except Exception:
            labels = {}
    outputs, sidecar = _output_manifests(graph, run_dir) if include_outputs else ([], {})
    manifest_hash = None
    if sidecar:
        try:
            _atomic_write_json(run_dir / OUTPUTS_MANIFEST_FILE, sidecar)
            manifest_hash = "sha256:" + hash_file(run_dir / OUTPUTS_MANIFEST_FILE)
        except Exception:
            log.debug("outputs manifest write failed", exc_info=True)
    mat_hash = meta.get("materialized_graph_hash")
    if not mat_hash and graph:
        mat_hash = graph_content_hash(graph)
    pipeline_source = meta.get("pipeline_source") or ("saved" if meta.get("pipeline_ref") else "adhoc")
    try:
        from app import __version__ as gv
    except Exception:
        gv = "unknown"
    record: dict[str, Any] = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "run_id": run_id,
        "status": status,
        "timestamp": _now(),
        "created_at": meta.get("created_at"),
        "duration_s": meta.get("duration_s"),
        "graph_hash": str(meta.get("graph_hash") or ""),
        "materialized_graph_hash": mat_hash,
        "graph_schema_version": str(graph.get("schema_version") or meta.get("graph_schema_version") or "unknown"),
        "graph_name": meta.get("graph_name") or gmeta.get("name"),
        "project": meta.get("project") or gmeta.get("project"),
        "pipeline_source": pipeline_source,
        "pipeline_version": meta.get("pipeline_ref") if isinstance(meta.get("pipeline_ref"), dict) else None,
        "node_implementation_versions": impls,
        "plugin_version": {str(k): str(v) for k, v in (versions or {}).items()},
        "plugin_code_hashes": {str(k): str(v) for k, v in (hashes or {}).items()},
        "external_inputs": inputs,
        "dataset_versions": ds_versions,
        "input_artifact_hashes": _input_artifact_hashes(meta, artifacts),
        "outputs": outputs,
        "outputs_manifest_hash": manifest_hash,
        "cache": _cache_rows(meta),
        "node_labels": labels,
        "model_version": meta.get("model_version") if isinstance(meta.get("model_version"), dict) else None,
        "environment": env_info,
        "runtime_version": f"python-{platform.python_version()}/{platform.system()}",
        "graphyn_version": str(env_info.get("graphyn_version") or gv),
        "worker_id": meta.get("worker_id"),
        "worker_software_version": meta.get("worker_software_version"),
        "configuration": {"node_ids": [str(n.get("id")) for n in _graph_nodes(graph)]},
        "seed": seed,
        "actor": str(meta.get("actor") or os.environ.get("GRAPHYN_ACTOR") or "system"),
        "trigger": str(meta.get("trigger") or "api"),
        "replay_of": meta.get("replay_of"),
        "error": meta.get("error") if status == "failed" else None,
        "error_type": meta.get("error_type") if status == "failed" else None,
        "failed_node_id": meta.get("failed_node_id") if status == "failed" else None,
        "node_count": meta.get("num_nodes"),
    }
    return record


def seal_run_record(
    run_dir: str | Path,
    *,
    run_id: str,
    status: str,
    meta: dict[str, Any],
    graph: dict[str, Any] | None = None,
    artifacts: list[Any] | None = None,
) -> dict[str, Any] | None:
    """Write immutable prove.json (v2), append to the project chain. First writer wins."""
    run_dir = Path(run_dir)
    path = run_dir / "prove.json"
    if path.exists():
        return None
    if graph is None:
        g = _read_json(run_dir / "graph.json")
        graph = g if isinstance(g, dict) else {}
    record = build_record(run_dir, run_id=run_id, status=status, meta=meta, graph=graph, artifacts=artifacts)
    project = record.get("project")
    cpath = chain_path(project)
    with _chain_lock, _FileLock(cpath.with_suffix(".lock")):
        if path.exists():
            return None
        rows = read_chain(project)
        prev = rows[-1].get("record_hash") if rows else None
        seq = len(rows) + 1
        record["chain"] = {"project": _chain_name(project), "seq": seq}
        record["previous_record_hash"] = prev
        record["record_hash"] = record_hash(record)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, path)
        entry = {"seq": seq, "run_id": run_id, "record_hash": record["record_hash"], "prev": prev,
                 "status": status, "ts": record["timestamp"]}
        cpath.parent.mkdir(parents=True, exist_ok=True)
        with open(cpath, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    return record


def load_record(run_dir: str | Path) -> dict[str, Any] | None:
    data = _read_json(Path(run_dir) / "prove.json")
    return data if isinstance(data, dict) else None


# ── verify ───────────────────────────────────────────────────────────────────


def _diff_tree(path: Path, expected: dict[str, Any]) -> dict[str, list[str]]:
    try:
        current = {rel: [size, sha] for rel, size, sha in tree_listing(path, limit=_MANIFEST_FILES_PER_ROOT)}
    except OSError:
        current = {}
    added = sorted(set(current) - set(expected))[:50]
    removed = sorted(set(expected) - set(current))[:50]
    modified = sorted(r for r in set(current) & set(expected) if list(current[r]) != list(expected[r]))[:50]
    return {"added": added, "removed": removed, "modified": modified}


def verify_run(run_dir: str | Path, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Re-hash graph snapshot, external inputs, outputs, record hash and chain."""
    run_dir = Path(run_dir)
    run_id = run_dir.name
    record = load_record(run_dir)
    meta = meta if isinstance(meta, dict) else (_read_json(run_dir / "meta.json") or {})
    checks: list[dict[str, Any]] = []
    out: dict[str, Any] = {"run_id": run_id, "verified_at": _now(), "checks": checks}
    if record is None:
        out.update({"status": "unsealed", "ok": False})
        return out

    has_hash = bool(record.get("record_hash"))
    if has_hash:
        actual = record_hash(record)
        checks.append({"check": "record_hash", "status": "pass" if actual == record["record_hash"] else "fail",
                       "expected": record["record_hash"], "actual": actual})
        project = record.get("project")
        rows = read_chain(project)
        idx = next((i for i, r in enumerate(rows) if r.get("run_id") == run_id), None)
        details: dict[str, Any] = {"project": _chain_name(project), "entry_found": idx is not None}
        status = "fail"
        if idx is not None:
            entry = rows[idx]
            prev_expected = rows[idx - 1].get("record_hash") if idx > 0 else None
            prev_ok = entry.get("prev") == prev_expected and record.get("previous_record_hash") == prev_expected
            hash_ok = entry.get("record_hash") == record.get("record_hash")
            details.update({"seq": entry.get("seq"), "prev_ok": prev_ok, "hash_ok": hash_ok,
                            "chain_length": len(rows)})
            status = "pass" if (prev_ok and hash_ok) else "fail"
        checks.append({"check": "chain", "status": status, "details": details})
    else:
        checks.append({"check": "record_hash", "status": "skipped",
                       "details": {"reason": f"legacy record schema {record.get('schema_version')}"}})

    graph = _read_json(run_dir / "graph.json")
    expected_mat = record.get("materialized_graph_hash") or meta.get("materialized_graph_hash")
    if isinstance(graph, dict):
        actual_mat = graph_content_hash(graph)
        if expected_mat:
            checks.append({"check": "graph_snapshot", "status": "pass" if actual_mat == expected_mat else "fail",
                           "expected": expected_mat, "actual": actual_mat})
        elif record.get("graph_hash") and record.get("graph_hash") == meta.get("graph_hash") and not meta.get("materialized_graph_hash"):
            checks.append({"check": "graph_snapshot", "status": "pass" if actual_mat == record["graph_hash"] else "fail",
                           "expected": record["graph_hash"], "actual": actual_mat})
    else:
        checks.append({"check": "graph_snapshot", "status": "missing", "expected": expected_mat, "actual": None})
    logical = _read_json(run_dir / LOGICAL_GRAPH_FILE)
    if isinstance(logical, dict) and record.get("graph_hash"):
        actual_l = graph_content_hash(logical)
        checks.append({"check": "logical_graph", "status": "pass" if actual_l == record["graph_hash"] else "fail",
                       "expected": record["graph_hash"], "actual": actual_l})

    checks.extend(check_external_inputs(record.get("external_inputs") or []))

    sidecar = _read_json(run_dir / OUTPUTS_MANIFEST_FILE)
    if record.get("outputs_manifest_hash"):
        try:
            actual_m = "sha256:" + hash_file(run_dir / OUTPUTS_MANIFEST_FILE)
        except OSError:
            actual_m = None
        checks.append({"check": "outputs_manifest", "status": "pass" if actual_m == record["outputs_manifest_hash"] else "fail",
                       "expected": record["outputs_manifest_hash"], "actual": actual_m})
    for row in record.get("outputs") or []:
        if not isinstance(row, dict) or not row.get("path"):
            continue
        path = resolve_path(str(row["path"]))
        if row.get("hash_mode") == "manifest":
            cur = hash_path(path, max_bytes=-1, max_files=-1)
        else:
            cur = hash_path(path, max_bytes=1 << 62, max_files=1 << 30)
        if cur.get("kind") == "missing":
            status = "missing"
        else:
            status = "pass" if cur.get("content_hash") == row.get("content_hash") else "changed"
        chk = {"check": "output", "target": row["path"], "node_id": row.get("node_id"), "status": status,
               "expected": row.get("content_hash"), "actual": cur.get("content_hash")}
        if status == "changed" and isinstance(sidecar, dict) and isinstance(sidecar.get(row["path"]), dict):
            chk["details"] = _diff_tree(path, sidecar[row["path"]])
        checks.append(chk)

    statuses = {c.get("status") for c in checks}
    if "fail" in statuses:
        overall = "fail"
    elif statuses & {"changed", "missing"}:
        overall = "changed"
    else:
        overall = "pass"
    out.update({"status": overall, "ok": overall == "pass",
                "record_schema_version": record.get("schema_version"),
                "record_hash": record.get("record_hash")})
    return out
