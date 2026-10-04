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
                  node_implementations(), capture_environment() (container
                  detection, image name/tag/digest, git commit via env /
                  BUILD_INFO.json / .git), run_environment() +
                  venv_environment() (per isolated-plugin venv libraries,
                  cached by site-packages mtime), resolve_model_lineage()
                  (record ``lineage``: source run + registered models),
                  collect_external_inputs() (named rows; write sinks and
                  the run's own outputs excluded), resolve_pipeline_ref(),
                  record_hash(), the per-project chain files
                  ``{project}/audit/chains/<project>.jsonl`` and the
                  ``runs/<id>/graph.logical.json`` / ``outputs_manifest.json``
                  sidecars.
Public Surface:   capture_run_start, seal_run_record, verify_run,
                  check_external_inputs, pipeline_drift, record_hash,
                  capture_environment, detect_container, build_info,
                  venv_environment, resolve_model_lineage, is_write_key,
                  chain_path, load_record, logical_graph_for_run,
                  RECORD_SCHEMA_VERSION
Must NOT:         Import app.api, orchestrator or app.domain; raise into run
                  lifecycle callers (capture/seal are best-effort).
Dependencies:     stdlib; app.core.runs.audit_hashing; app.core.config;
                  app.core.nodes registry / plugins runtime registry / store,
                  app.core.pipelines (lazy); app.core.paths.workspace_paths (lazy);
                  app.core.mlops.model_registry, app.core.artifacts (lazy).
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


_BUILD_INFO_FILE = "BUILD_INFO.json"


def _build_info_paths() -> list[Path]:
    paths: list[Path] = []
    env = (os.environ.get("GRAPHYN_BUILD_INFO") or "").strip()
    if env:
        paths.append(Path(env))
    repo = Path(__file__).resolve().parents[3]
    paths.extend([repo / _BUILD_INFO_FILE, Path("/app") / _BUILD_INFO_FILE])
    return paths


def build_info() -> dict[str, Any]:
    """Baked build facts (``BUILD_INFO.json`` written by ``docker build``), or {}."""
    for path in _build_info_paths():
        data = _read_json(path) if path.is_file() else None
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items() if v not in (None, "")}
    return {}


def _git_from_dotgit() -> str | None:
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


def _git_commit_info(info: dict[str, Any] | None = None) -> tuple[str | None, str | None]:
    """``(commit, source)``: env GRAPHYN_GIT_SHA → BUILD_INFO.json → .git."""
    env = (os.environ.get("GRAPHYN_GIT_SHA") or "").strip()
    if env:
        return env, "env:GRAPHYN_GIT_SHA"
    info = build_info() if info is None else info
    baked = str(info.get("git_sha") or info.get("git_commit") or "").strip()
    if baked:
        return baked, _BUILD_INFO_FILE
    sha = _git_from_dotgit()
    return (sha, ".git") if sha else (None, None)


def _git_commit() -> str | None:
    return _git_commit_info()[0]


_HEX64_RE = re.compile(r"(?<![0-9a-f])([0-9a-f]{64})(?![0-9a-f])")
_CGROUP_HINT_RE = re.compile(r"docker|containerd|kubepods|libpod|crio")
_ETC_MOUNTS = ("/etc/hostname", "/etc/hosts", "/etc/resolv.conf")


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def detect_container() -> dict[str, Any]:
    """Best-effort container detection (docker / podman / kubernetes).

    Signals: ``/.dockerenv``, ``/run/.containerenv`` (podman),
    ``KUBERNETES_SERVICE_HOST``, ``/proc/1/cgroup`` / ``/proc/self/cgroup`` /
    ``/proc/self/mountinfo`` mentioning docker/containerd/kubepods (container
    id = 64-hex), ``container`` env. Image facts come from env
    ``GRAPHYN_IMAGE`` / ``GRAPHYN_IMAGE_DIGEST`` or ``BUILD_INFO.json``.
    """
    signals: list[str] = []
    runtime: str | None = None
    if os.path.exists("/.dockerenv"):
        signals.append("/.dockerenv")
        runtime = "docker"
    if os.path.exists("/run/.containerenv"):
        signals.append("/run/.containerenv")
        runtime = runtime or "podman"
    if (os.environ.get("KUBERNETES_SERVICE_HOST") or "").strip():
        signals.append("env:KUBERNETES_SERVICE_HOST")
        runtime = runtime or "kubernetes"
    env_container = (os.environ.get("container") or "").strip()
    if env_container:
        signals.append("env:container")
        runtime = runtime or env_container
    cid: str | None = None
    for path in ("/proc/1/cgroup", "/proc/self/cgroup"):
        text = _read_text(path)
        for line in text.splitlines():
            if not _CGROUP_HINT_RE.search(line):
                continue
            if path not in signals:
                signals.append(path)
            runtime = runtime or ("kubernetes" if "kubepods" in line else "podman" if "libpod" in line else "docker")
            m = _HEX64_RE.search(line)
            if m and cid is None:
                cid = m.group(1)
    # mountinfo: only the bind mounts a runtime puts on /etc/hostname etc.
    # (the host's own mountinfo lists other containers' overlay/shm mounts).
    for line in _read_text("/proc/self/mountinfo").splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[4] not in _ETC_MOUNTS:
            continue
        if not re.search(r"docker|containers|containerd|kubelet|libpod", fields[3]):
            continue
        if "/proc/self/mountinfo" not in signals:
            signals.append("/proc/self/mountinfo")
        runtime = runtime or ("kubernetes" if "kubelet" in fields[3] else "podman" if "libpod" in fields[3] else "docker")
        m = _HEX64_RE.search(fields[3])
        if m and cid is None:
            cid = m.group(1)
    if cid is None and signals:
        # cgroup v2 hides the id; docker sets HOSTNAME to the 12-char short id.
        host = (os.environ.get("HOSTNAME") or socket.gethostname() or "").strip()
        if re.fullmatch(r"[0-9a-f]{12}", host):
            cid = host
    return {"in_container": bool(signals), "runtime": runtime, "container_id": cid, "signals": signals}


def _container_info() -> tuple[str | None, str | None]:
    """Back-compat ``(image digest, container id)``."""
    digest = (os.environ.get("GRAPHYN_IMAGE_DIGEST") or "").strip() or None
    return digest, detect_container().get("container_id")


def _image_facts(container: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    name = (os.environ.get("GRAPHYN_IMAGE") or "").strip() or str(info.get("image") or "").strip() or None
    digest = (os.environ.get("GRAPHYN_IMAGE_DIGEST") or "").strip() or str(info.get("image_digest") or "").strip() or None
    tag = None
    if name and ":" in name.rsplit("/", 1)[-1]:
        tag = name.rsplit(":", 1)[1]
    label = None
    if name and digest:
        label = f"{name}@{digest}" if not name.endswith(digest) else name
    elif name or digest:
        label = name or digest
    elif container.get("in_container"):
        cid = str(container.get("container_id") or "")[:12]
        label = f"{container.get('runtime') or 'container'} container" + (f" {cid}" if cid else "") + " (image not recorded)"
    return {"image": label, "image_name": name, "image_tag": tag, "image_digest": digest}


def capture_environment(*, refresh: bool = False) -> dict[str, Any]:
    """Python / OS / key library versions / container image / git commit (cached)."""
    global _env_cache
    if _env_cache is not None and not refresh:
        return dict(_env_cache)
    libs: dict[str, str | None] = {}
    for name in _LIBS:
        ver = _dist_version(name)
        if ver is not None or name in ("numpy", "tensorflow", "keras", "librosa", "torch", "onnx"):
            libs[name] = ver
    info = build_info()
    container = detect_container()
    image = _image_facts(container, info)
    git_sha, git_source = _git_commit_info(info)
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
        **image,
        "container_image_digest": image["image_digest"],
        "container_id": container.get("container_id"),
        "container": container,
        "git_commit": git_sha,
        "git_source": git_source,
        "build_info": info or None,
        "graphyn_version": _dist_version("graphyn-sdk") or gv,
        "backend": (os.environ.get("GRAPHYN_BACKEND") or "local_python").strip() or "local_python",
    }
    _env_cache = env
    return dict(env)


def run_environment(impls: dict[str, Any] | None = None) -> dict[str, Any]:
    """Host environment + ``plugin_environments`` of the isolated plugins used."""
    env = capture_environment()
    try:
        env["plugin_environments"] = plugin_environments(impls or {})
    except Exception:
        env["plugin_environments"] = {}
    return env


# Key libraries reported per isolated plugin venv (plus a full-freeze hash).
_VENV_KEY_LIBS = _LIBS + (
    "tf-keras", "ml-dtypes", "h5py", "protobuf", "tensorflow-io-gcs-filesystem",
    "transformers", "datasets", "tokenizers", "sentencepiece", "opencv-python",
    "opencv-python-headless", "pillow", "numba", "llvmlite", "webrtcvad",
)
_venv_cache: dict[str, tuple[tuple, dict[str, Any]]] = {}
_venv_cache_lock = threading.Lock()


def _venv_root(venv_python: str | Path) -> Path:
    """Venv root WITHOUT following the interpreter symlink.

    ``<venv>/bin/python`` is usually a symlink to the base interpreter;
    resolving it would scan the API host's site-packages instead of the venv.
    """
    p = Path(os.path.abspath(str(venv_python)))
    root = p.parent.parent
    if (root / "pyvenv.cfg").is_file():
        return root
    for cand in (p.parent, p.parent.parent.parent):
        if (cand / "pyvenv.cfg").is_file():
            return cand
    return root


def _site_packages(root: Path) -> list[Path]:
    return [*root.glob("lib/python*/site-packages"), *root.glob("Lib/site-packages")]


def _norm_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def venv_environment(venv_python: str | Path) -> dict[str, Any]:
    """Library versions inside an isolated plugin venv (dist-info scan).

    ``{venv, python, libraries (key libs), package_count, freeze_hash}`` —
    ``freeze_hash`` is sha256 over the sorted ``name==version`` list, so any
    package change in the venv changes it. Cached per venv path, invalidated
    by the site-packages directory mtime (installs/uninstalls touch it).
    """
    root = _venv_root(venv_python)
    sps = _site_packages(root)
    sig: tuple = tuple((str(sp), sp.stat().st_mtime_ns) for sp in sps if sp.is_dir())
    key = str(root)
    with _venv_cache_lock:
        hit = _venv_cache.get(key)
        if hit is not None and hit[0] == sig:
            return dict(hit[1])
    wanted = {_norm_dist(n) for n in _VENV_KEY_LIBS}
    packages: dict[str, str] = {}
    for sp in sps:
        try:
            infos = list(sp.glob("*.dist-info"))
        except OSError:
            continue
        for info in infos:
            stem = info.name[: -len(".dist-info")]
            if "-" not in stem:
                continue
            name, ver = stem.rsplit("-", 1)
            packages[_norm_dist(name)] = ver
    python = None
    cfg = root / "pyvenv.cfg"
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip().lower() in ("version", "version_info"):
                python = v.strip()
                break
    except OSError:
        pass
    freeze = "\n".join(f"{n}=={v}" for n, v in sorted(packages.items()))
    out = {
        "venv": str(root),
        "python": python,
        "libraries": {n: v for n, v in sorted(packages.items()) if n in wanted},
        "package_count": len(packages),
        "freeze_hash": ("sha256:" + hashlib.sha256(freeze.encode("utf-8")).hexdigest()) if packages else None,
    }
    with _venv_cache_lock:
        _venv_cache[key] = (sig, out)
    return dict(out)


def _venv_libraries(venv_python: str) -> dict[str, str]:
    """Key library versions inside an isolated plugin venv (back-compat)."""
    try:
        return dict(venv_environment(venv_python).get("libraries") or {})
    except Exception:
        return {}


def plugin_environments(impls: dict[str, Any]) -> dict[str, Any]:
    """``plugin → venv_environment`` for the isolated plugins a run used."""
    out: dict[str, Any] = {}
    for impl in (impls or {}).values():
        if not isinstance(impl, dict):
            continue
        plugin = impl.get("plugin")
        venv_py = impl.get("venv_python")
        if not plugin or not venv_py or plugin in out:
            continue
        try:
            env = venv_environment(venv_py)
        except Exception:
            continue
        out[str(plugin)] = {**env, "plugin_version": impl.get("version")}
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
        info["venv_python"] = str(spec.venv_python)
        try:
            venv_env = venv_environment(spec.venv_python)
        except Exception:
            venv_env = {}
        if venv_env.get("libraries"):
            info["venv_libraries"] = venv_env["libraries"]
        if venv_env.get("freeze_hash"):
            info["venv_freeze_hash"] = venv_env["freeze_hash"]
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


_WRITE_KEY_RE = re.compile(
    r"^(?:out|output|outputs|dest|destination|export|save|target_dir|log|cache|checkpoint)(?:_|$)"
    r"|(?:^|_)(?:output|outputs|out|dest|destination|export|save)_?(?:path|dir|file|folder|root|uri)?$"
)


def is_write_key(key: str) -> bool:
    """Config keys that name write sinks (outputs), never external inputs."""
    k = str(key or "").strip().lower()
    if not k:
        return False
    if k in _WRITE_KEYS:
        return True
    if k in _INPUT_KEYS:
        return False
    return bool(_WRITE_KEY_RE.search(k))


# Quoted path-ish literals inside code/source config strings (python_code).
_CODE_ASSIGN_RE = re.compile(
    r"""(?:["']([A-Za-z_][A-Za-z0-9_]*)["']\s*:|\b([A-Za-z_][A-Za-z0-9_]*)\s*=)\s*["']([^"'\n]{1,512})["']"""
)
_CODE_LITERAL_RE = re.compile(r"""["']((?:workspace|datasets|artifacts|examples)/[^"'\n]{1,500}|/[^"'\n]{2,500})["']""")


def _code_paths(text: str) -> list[tuple[str, str]]:
    """``(inner key, path)`` for path literals in a multi-line code string."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _CODE_ASSIGN_RE.finditer(text):
        inner = m.group(1) or m.group(2) or ""
        val = m.group(3).strip()
        if val and val not in seen and _PATHISH_RE.search(val) and "/" in val and "://" not in val:
            seen.add(val)
            found.append((inner, val))
    for m in _CODE_LITERAL_RE.finditer(text):
        val = m.group(1).strip()
        if val and val not in seen and "://" not in val:
            seen.add(val)
            found.append(("", val))
    return found


def _node_label(node: dict[str, Any]) -> str:
    return str(node.get("label") or node.get("id") or "").strip()


def _specific_root(path: Path) -> bool:
    """False for broad write roots (workspace, workspace/artifacts, /, …) that
    would swallow legitimate inputs living elsewhere under them."""
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(_project_root()))
    except ValueError:
        return len(Path(path).parts) > 3
    if rel.startswith(".."):
        return len(Path(os.path.abspath(path)).parts) > 3
    parts = [p for p in Path(rel).parts if p not in (".", "")]
    return len(parts) >= 2


def _write_roots(graph: dict[str, Any], run_id: str) -> list[Path]:
    """Resolved write locations of this run (output-ish config keys + run dir)."""
    roots: list[Path] = []
    for node in _graph_nodes(graph):
        for key, raw in _walk_config(node.get("config") or {}):
            if not raw or not is_write_key(key):
                continue
            text = raw.strip()
            if not text or "\n" in text or "://" in text or len(text) > 1024:
                continue
            try:
                cand = resolve_path(text)
            except Exception:
                continue
            if _specific_root(cand):
                roots.append(cand)
    if run_id:
        try:
            from app.core.config import runs_dir

            roots.append(runs_dir() / run_id)
        except Exception:
            pass
    return roots


def _under_any(path: Path, roots: list[Path]) -> bool:
    try:
        p = Path(os.path.abspath(path))
    except Exception:
        return False
    for r in roots:
        try:
            ra = Path(os.path.abspath(r))
        except Exception:
            continue
        if p == ra or ra in p.parents:
            return True
    return False


def collect_external_inputs(graph: dict[str, Any], run_id: str = "") -> list[dict[str, Any]]:
    """Every external path a node reads (config path strings), hashed.

    Each row names its source: ``node_id`` / ``node_label`` / ``key`` (config
    key; ``source:model_path`` for a literal inside a code string) and a
    human ``label`` (``"<node label> · <key>"``). Write sinks are excluded:
    output-ish config keys (``output_path`` / ``out_*`` / ``*_output_dir`` …),
    anything under one of this graph's output locations, and anything under
    this run's own scope (``…/runs/<run_id>``) — a run's own output (e.g. a
    package archive left from a previous run at the same output path) is
    never recorded as its input.
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    write_roots = _write_roots(graph, run_id)
    for node in _graph_nodes(graph):
        nid = str(node.get("id") or "")
        ntype = _node_type(node)
        label = _node_label(node)
        candidates: list[tuple[str, str, bool]] = []  # (key, text, from_code)
        for key, raw in _walk_config(node.get("config") or {}):
            if not raw or not raw.strip() or "://" in raw:
                continue
            if "\n" in raw.strip():
                for inner, val in _code_paths(raw):
                    if inner and is_write_key(inner):
                        continue
                    candidates.append((f"{key}:{inner}" if inner else key, val, True))
                continue
            if is_write_key(key):
                continue
            candidates.append((key, raw.strip(), False))
        for key, text, from_code in candidates:
            if len(text) > 1024:
                continue
            if run_id and _run_scoped(text, run_id):
                continue  # produced by this run
            base_key = key.split(":", 1)[-1] if from_code else key
            known = (not from_code) and (base_key in _INPUT_KEYS or base_key.endswith(("_path", "_dir", "_file")))
            if not from_code and not known and not _PATHISH_RE.search(text):
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
            if _under_any(path, write_roots):
                continue  # this run's own output location
            exists = path.exists()
            if not exists and (from_code or not known):
                continue
            if (nid, text) in seen:
                continue
            seen.add((nid, text))
            res = hash_path(path)
            entry = {
                "node_id": nid,
                "node_type": ntype,
                "node_label": label or nid,
                "key": key,
                "label": f"{label or nid} · {key}",
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

    impls: dict[str, Any] = {}
    try:
        impls, versions, hashes = node_implementations(_node_type(n) for n in _graph_nodes(materialized_graph))
        _w("node_implementations", impls)
        _w("plugin_version", versions)
        _w("plugin_code_hashes", hashes)
    except Exception:
        log.debug("node implementation capture failed", exc_info=True)
    try:
        _w("environment_info", run_environment(impls))
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


def _art_get(a: Any, key: str) -> Any:
    return a.get(key) if isinstance(a, dict) else getattr(a, key, None)


def _input_artifact_hashes(meta: dict[str, Any], artifacts: list[Any] | None, run_id: str = "") -> list[str]:
    """Content hashes of artifacts this run CONSUMED but did not produce.

    ``artifacts`` are the run's own registered (output) artifacts — they are
    never inputs. Consumed ids come from the run's provenance records
    (``input_artifact_ids``); ids/hashes produced by this run are dropped.
    """
    produced_ids = {str(_art_get(a, "artifact_id")) for a in artifacts or [] if _art_get(a, "artifact_id")}
    produced_hashes = {str(_art_get(a, "content_hash")) for a in artifacts or [] if _art_get(a, "content_hash")}
    if isinstance(meta.get("input_artifact_hashes"), list):
        return [str(x) for x in meta["input_artifact_hashes"] if str(x) not in produced_hashes]
    if not run_id:
        return []
    consumed: list[str] = []
    try:
        from app.core.artifacts.provenance import ProvenanceStore

        for rec in ProvenanceStore().find_by_run(run_id):
            for aid in getattr(rec, "input_artifact_ids", None) or []:
                if aid and aid not in produced_ids and aid not in consumed:
                    consumed.append(str(aid))
    except Exception:
        return []
    out: list[str] = []
    if consumed:
        try:
            from app.core.artifacts.artifact_store import ArtifactStore

            store = ArtifactStore()
            for aid in consumed[:500]:
                try:
                    h = store.get(aid).content_hash
                except Exception:
                    continue
                if h and h not in produced_hashes and h not in out:
                    out.append(str(h))
        except Exception:
            return out
    return out


# ── model lineage ────────────────────────────────────────────────────────────


def _registry_models() -> list[dict[str, Any]]:
    try:
        from app.core.mlops.model_registry import list_models

        return [m for m in list_models() if isinstance(m, dict)]
    except Exception:
        return []


def _model_entry(name: str, stage: str, rec: dict[str, Any], *, match: str, **extra: Any) -> dict[str, Any]:
    art = str(rec.get("artifact_path") or rec.get("path") or "")
    entry: dict[str, Any] = {
        "name": name,
        "stage": stage,
        "version": stage,
        "run_id": rec.get("run_id"),
        "artifact_path": art or None,
        "node_id": rec.get("node_id"),
        "format": rec.get("format"),
        "model_hash": None,
        "match": match,
        **{k: v for k, v in extra.items() if v is not None},
    }
    if art:
        try:
            res = hash_path(resolve_path(art))
            entry["model_hash"] = res.get("content_hash")
            entry["hash_mode"] = res.get("hash_mode")
        except Exception:
            pass
    return entry


def _same_or_nested(a: Path, b: Path) -> bool:
    try:
        pa, pb = Path(os.path.abspath(a)), Path(os.path.abspath(b))
    except Exception:
        return False
    return pa == pb or pb in pa.parents or pa in pb.parents


def resolve_model_lineage(meta: dict[str, Any], inputs: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Which registered model(s) this run consumed / shipped.

    Sources: the declared payload ``lineage.model`` (meta ``lineage_request``,
    match ``declared``) and any external input whose path is (inside) a
    registered model stage's artifact (match ``input_path``). Each model row:
    ``{name, stage, version, run_id, artifact_path, model_hash, match, …}``.
    """
    req = meta.get("lineage_request") if isinstance(meta.get("lineage_request"), dict) else {}
    source_run = str(meta.get("source_run_id") or req.get("source_run_id") or "").strip() or None
    if source_run:
        try:
            from app.core.config import runs_dir
            from app.core.runs.run_resolve import resolve_run_id_soft

            source_run = resolve_run_id_soft(runs_dir(), source_run)
        except Exception:
            pass
    models: list[dict[str, Any]] = []
    registry = {str(m.get("name")): m for m in _registry_models()}
    declared = req.get("model") if isinstance(req.get("model"), dict) else None
    if declared and declared.get("name"):
        name = str(declared["name"])
        want = str(declared.get("stage") or declared.get("version") or "").strip()
        rec = registry.get(name)
        stages = rec.get("stages") if isinstance(rec, dict) and isinstance(rec.get("stages"), dict) else {}
        stage = want if want in stages else (want or None)
        if stage is None:
            stage = next((s for s in ("prod", "staging", "latest") if s in stages), None)
        srec = stages.get(stage) if stage else None
        if isinstance(srec, dict):
            models.append(_model_entry(name, str(stage), srec, match="declared", requested_version=declared.get("version")))
        else:
            models.append({
                "name": name, "stage": stage, "version": declared.get("version") or stage,
                "run_id": None, "artifact_path": None, "model_hash": None,
                "match": "declared", "resolved": False,
            })
    seen = {(m.get("name"), m.get("stage")) for m in models}
    for row in inputs or []:
        if not isinstance(row, dict) or not row.get("path"):
            continue
        try:
            ipath = resolve_path(str(row.get("resolved") or row["path"]))
        except Exception:
            continue
        for name, rec in registry.items():
            stages = rec.get("stages") if isinstance(rec.get("stages"), dict) else {}
            for stage, srec in stages.items():
                if not isinstance(srec, dict) or (name, stage) in seen:
                    continue
                art = srec.get("artifact_path") or srec.get("path")
                if not art:
                    continue
                try:
                    apath = resolve_path(str(art))
                except Exception:
                    continue
                if _same_or_nested(ipath, apath):
                    seen.add((name, stage))
                    models.append(_model_entry(name, str(stage), srec, match="input_path",
                                               node_id_input=row.get("node_id"), key=row.get("key")))
    if not models and not source_run and not meta.get("source_artifact_id"):
        return None
    return {
        "source_run_id": source_run,
        "source_artifact_id": meta.get("source_artifact_id"),
        "models": models,
    }


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
    env_info = meta.get("environment_info") if isinstance(meta.get("environment_info"), dict) else run_environment(impls)
    if isinstance(env_info, dict) and "plugin_environments" not in env_info:
        env_info = {**env_info, "plugin_environments": plugin_environments(impls if isinstance(impls, dict) else {})}
    inputs = meta.get("external_inputs")
    if not isinstance(inputs, list):
        inputs = collect_external_inputs(graph, run_id)
    ds_versions = meta.get("dataset_versions") if isinstance(meta.get("dataset_versions"), list) else dataset_versions_from_inputs(inputs)
    try:
        lineage = resolve_model_lineage(meta, inputs)
    except Exception:
        log.debug("model lineage resolve failed", exc_info=True)
        lineage = None
    model_version = meta.get("model_version") if isinstance(meta.get("model_version"), dict) else None
    if model_version is None and lineage and lineage.get("models"):
        first = lineage["models"][0]
        model_version = {k: first.get(k) for k in ("name", "stage", "version", "run_id", "model_hash")}
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
        "input_artifact_hashes": _input_artifact_hashes(meta, artifacts, run_id),
        "outputs": outputs,
        "outputs_manifest_hash": manifest_hash,
        "cache": _cache_rows(meta),
        "node_labels": labels,
        "model_version": model_version,
        "lineage": lineage,
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
