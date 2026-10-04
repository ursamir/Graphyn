# app/core/plugins/isolated_executor.py
"""
Bounded Context:  BC3 / BC5 — Isolated plugin execution bridge
Responsibility:   Run an isolated plugin node's process() in a subprocess
                  using that plugin's venv Python, with pickle IPC via files.
Owns:             run_isolated_node(), recast_plugin_types(); live parsing
                  of worker ``@@GRAPHYN_PROGRESS@@ <json>`` stderr lines
                  forwarded as node_progress events (app.core.nodes.progress);
                  IsolatedNodeError (real worker exception: worker
                  ``error.json`` first, else noise-filtered stderr traceback).
Public Surface:   run_isolated_node, recast_plugin_types, load_isolated_outputs,
                  IsolatedNodeError, parse_worker_stderr,
                  hydrate_platform_models (via app.core.plugins.hydrate)
Must NOT:         Import from app.domain or app.api.
Dependencies:     stdlib, runtime_registry, app.core.nodes.progress (lazy)
Reason To Change: IPC protocol or worker CLI changes.

IPC / pickle (B3)
-----------------
Worker *results* are unpickled in the host with a restricted unpickler.
Only builtins, a small stdlib set, numpy reconstruct helpers, and
``app.models.*`` types are allowed. Unknown globals fail closed
(``pickle.UnpicklingError``). Isolated plugins remain trusted for
*inputs* pickled by the host; do not treat pickle as a sandbox.

Host *inputs* may contain PortDataType instances defined in dynamically loaded
plugin modules (``_graphyn_plugin_*.types``). Those module names are not
importable in the worker, so pickle.dumps would fail. Before dumping, recast
such objects onto the matching ``app.models.*`` class by ``__name__``.
Override worker timeout with GRAPHYN_PLUGIN_ISOLATED_TIMEOUT (seconds).
Default: 3600.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Worker → host envelope marker (avoid colliding with a port named "outputs").
ISOLATED_ENVELOPE_MARK = "__graphyn_isolated_envelope__"


@dataclass(frozen=True)
class IsolatedResult:
    """Port outputs plus optional ``publish_files`` inventories from the worker."""

    outputs: dict[str, Any]
    published_file_trees: tuple[dict[str, Any], ...] = field(default_factory=tuple)

from app.core.plugins.hydrate import coerce_node_inputs, hydrate_platform_models
from app.core.plugins.runtime_registry import IsolatedPluginSpec

__all__ = [
    "ISOLATED_ENVELOPE_MARK",
    "IsolatedNodeError",
    "IsolatedResult",
    "RestrictedUnpickler",
    "coerce_node_inputs",
    "hydrate_platform_models",
    "load_isolated_outputs",
    "load_isolated_result",
    "parse_worker_stderr",
    "recast_plugin_types",
    "run_isolated_node",
]

log = logging.getLogger(__name__)

# Host-side unpickle allowlist for worker outputs (fail closed).
# Module membership alone is NOT enough — ``builtins`` exports ``eval``/``exec``.
_ALLOWED_PICKLE_MODULES = frozenset(
    {
        "builtins",
        "collections",
        "collections.abc",
        "copyreg",
        "datetime",
        "decimal",
        "numbers",
        "pathlib",
        "numpy",
        "numpy.core",
        "numpy.core.multiarray",
        "numpy.core.numeric",
        "numpy._core",
        "numpy._core.multiarray",
        "numpy._core.numeric",
        "numpy.dtypes",
        "numpy.ma",
        "numpy.ma.core",
    }
)

# Name-level allowlists for modules that also export dangerous callables.
_ALLOWED_BUILTINS = frozenset(
    {
        "NoneType",
        "bool",
        "bytearray",
        "bytes",
        "complex",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "object",
        "set",
        "str",
        "tuple",
        "type",
    }
)
_ALLOWED_COLLECTIONS = frozenset(
    {
        "OrderedDict",
        "defaultdict",
        "deque",
        "Counter",
        "ChainMap",
        "UserDict",
        "UserList",
        "UserString",
    }
)
_ALLOWED_COPYREG = frozenset({"_reconstructor", "__newobj__", "__newobj_ex__"})
_ALLOWED_PATHLIB = frozenset({"PurePath", "PurePosixPath", "PureWindowsPath", "Path", "PosixPath", "WindowsPath"})
_ALLOWED_NUMPY_MULTIARRAY = frozenset(
    {
        "_reconstruct",
        "scalar",
        "ndarray",
        "dtype",
        "_frombuffer",
    }
)


# Private (``_``-prefixed) names that legitimate pickles need. Everything
# else starting with ``_`` is refused (``numpy._pytesttester`` etc.).
_ALLOWED_PRIVATE_NAMES = _ALLOWED_COPYREG | frozenset(
    {"_reconstruct", "_frombuffer", "_mareconstruct"}
)
# numpy callables (non-class) allowed from numpy.* modules.
_ALLOWED_NUMPY_CALLABLES = _ALLOWED_NUMPY_MULTIARRAY | frozenset({"_frombuffer", "_mareconstruct"})
# numpy classes with filesystem / URL side effects on construction.
_DENIED_NUMPY_NAMES = frozenset({"memmap", "DataSource", "load", "save", "savez", "fromfile", "tofile"})


class RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that refuses globals outside a known port/artifact set.

    ``name`` must be a plain identifier: protocol-4 ``STACK_GLOBAL`` accepts
    dotted names and ``pickle.Unpickler.find_class`` would walk them
    attribute-by-attribute (``numpy`` + ``_pytesttester.os.getpid`` reaches
    ``os.getpid``), so any ``.`` is refused outright.
    """

    def find_class(self, module: str, name: str) -> Any:
        if not isinstance(name, str) or not name or "." in name:
            raise pickle.UnpicklingError(
                f"Refusing dotted/invalid global name {module}.{name!r} from isolated worker output"
            )
        if module.startswith("app.models."):
            if name.startswith("_"):
                raise pickle.UnpicklingError(f"Refusing private name {module}.{name}")
            obj = super().find_class(module, name)
            owner = str(getattr(obj, "__module__", "") or "")
            if not owner.startswith("app.models.") or not callable(obj):
                # Re-exported foreign objects (``from os import system``) fail closed.
                raise pickle.UnpicklingError(
                    f"Refusing {module}.{name}: not defined under app.models ({owner or '?'})"
                )
            return obj
        if module not in _ALLOWED_PICKLE_MODULES:
            raise pickle.UnpicklingError(
                f"Refusing to unpickle {module}.{name} from isolated worker output "
                "(module not in the host allowlist)"
            )
        if name.startswith("_") and name not in _ALLOWED_PRIVATE_NAMES:
            raise pickle.UnpicklingError(f"Refusing private name {module}.{name}")
        if module == "builtins" and name not in _ALLOWED_BUILTINS:
            raise pickle.UnpicklingError(f"Refusing builtins.{name}")
        if module in {"collections", "collections.abc"} and name not in _ALLOWED_COLLECTIONS:
            # collections.abc is mostly ABCs — still refuse unknown names.
            if module == "collections.abc":
                raise pickle.UnpicklingError(f"Refusing {module}.{name}")
            raise pickle.UnpicklingError(f"Refusing collections.{name}")
        if module == "copyreg" and name not in _ALLOWED_COPYREG:
            raise pickle.UnpicklingError(f"Refusing copyreg.{name}")
        if module == "pathlib" and name not in _ALLOWED_PATHLIB:
            raise pickle.UnpicklingError(f"Refusing pathlib.{name}")
        if module.endswith("multiarray") and name not in _ALLOWED_NUMPY_MULTIARRAY:
            raise pickle.UnpicklingError(f"Refusing {module}.{name}")
        if module == "numpy" or module.startswith("numpy."):
            if name in _DENIED_NUMPY_NAMES:
                raise pickle.UnpicklingError(f"Refusing {module}.{name}")
            obj = super().find_class(module, name)
            if not isinstance(obj, type) and name not in _ALLOWED_NUMPY_CALLABLES:
                raise pickle.UnpicklingError(
                    f"Refusing {module}.{name}: only numpy classes / reconstruct helpers"
                )
            return obj
        obj = super().find_class(module, name)
        if isinstance(obj, type(pickle)):
            raise pickle.UnpicklingError(f"Refusing module object {module}.{name}")
        return obj


def _is_dynamic_plugin_module(module: str) -> bool:
    """True if *module* is a host-loaded plugin namespace pickle cannot import."""
    if not module:
        return False
    return module.startswith("_graphyn_plugin_") or "graphyn_plugin" in module


def _platform_type_for_name(name: str) -> type | None:
    """Resolve *name* (DatasetArtifact, ModelArtifact, ...) to an app.models class."""
    try:
        import app.models as models
    except Exception:  # pragma: no cover
        return None
    obj = getattr(models, name, None)
    return obj if isinstance(obj, type) else None


def recast_plugin_types(obj: Any) -> Any:
    """Rewrite dynamically loaded plugin types onto stable ``app.models`` classes.

    Walks dict/list/tuple trees. Objects whose ``type.__module__`` is a
    ``_graphyn_plugin_*`` (or contains ``graphyn_plugin``) are reconstructed
    as the platform class with the same ``__name__`` via model_validate /
    model_dump when available.
    """
    if obj is None or isinstance(obj, (str, bytes, int, float, bool, complex)):
        return obj
    if isinstance(obj, dict):
        return {k: recast_plugin_types(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [recast_plugin_types(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(recast_plugin_types(v) for v in obj)

    cls = type(obj)
    module = getattr(cls, "__module__", "") or ""
    if not _is_dynamic_plugin_module(module):
        return obj
    target = _platform_type_for_name(cls.__name__)
    if target is None or target is cls:
        # Cross-host Mode B: no shared dynamic module — emit plain dict/list.
        try:
            if hasattr(obj, "model_dump"):
                return recast_plugin_types(obj.model_dump(mode="python"))
        except Exception:
            pass
        if hasattr(obj, "__dict__"):
            payload = {k: v for k, v in vars(obj).items() if not k.startswith("_")}
            return recast_plugin_types(payload)
        return obj
    try:
        if hasattr(obj, "model_dump") and hasattr(target, "model_validate"):
            return target.model_validate(obj.model_dump())
        if hasattr(obj, "__dict__"):
            payload = {k: v for k, v in vars(obj).items() if not k.startswith("_")}
            return target(**payload)
    except Exception as exc:
        log.warning(
            "isolated_executor: could not recast %s.%s onto %s: %s",
            module,
            cls.__name__,
            getattr(target, "__module__", "?"),
            exc,
        )
        try:
            if hasattr(obj, "model_dump"):
                return recast_plugin_types(obj.model_dump(mode="python"))
        except Exception:
            pass
    return obj



def terminate_process_group(pid: int) -> None:
    """Best-effort SIGTERM+SIGKILL of a session/process group (Unix)."""
    if pid <= 0:
        return
    if os.name == "nt":
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            return
        if sig == signal.SIGTERM:
            try:
                os.waitpid(-pid, os.WNOHANG)
            except Exception:
                pass


_CANCEL_POLL_S = 0.5


def _run_isolated_subprocess(
    cmd: list[str],
    *,
    env: dict[str, str],
    timeout: float,
    cancel_check: Callable[[], bool] | None = None,
    cancel_poll_s: float = _CANCEL_POLL_S,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> subprocess.CompletedProcess:
    """Run the worker in a new session; terminate the group on timeout/cancel/failure.

    Isolated trainer workers can spawn extra Python processes. Killing only
    the leader left leaked ``python -m app.core.plugins.worker`` rows in htop.

    When ``cancel_check`` is provided, communicate is polled in short slices so
    mid-flight cancel can SIGTERM+SIGKILL the process group promptly.

    When ``on_progress`` is provided, stdout/stderr are drained by reader
    threads instead of ``communicate``: stderr lines starting with
    ``@@GRAPHYN_PROGRESS@@`` are parsed live and passed to ``on_progress``
    (and removed from the captured stderr); everything else is kept.
    """
    if on_progress is not None:
        return _run_isolated_subprocess_streaming(
            cmd,
            env=env,
            timeout=timeout,
            cancel_check=cancel_check,
            cancel_poll_s=cancel_poll_s,
            on_progress=on_progress,
        )
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    pgid = proc.pid

    def _reap_after_kill() -> tuple[str, str]:
        try:
            return proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            return ("", "")

    try:
        if cancel_check is None:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                terminate_process_group(pgid)
                stdout, stderr = _reap_after_kill()
                raise RuntimeError(
                    f"Isolated plugin worker timed out after {timeout}s "
                    "(process group terminated)"
                ) from None
        else:
            deadline = time.monotonic() + float(timeout)
            poll = max(0.05, float(cancel_poll_s))
            stdout = stderr = ""
            while True:
                if cancel_check():
                    terminate_process_group(pgid)
                    stdout, stderr = _reap_after_kill()
                    raise RuntimeError(
                        "cancelled by control plane "
                        "(isolated process group terminated)"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    terminate_process_group(pgid)
                    stdout, stderr = _reap_after_kill()
                    raise RuntimeError(
                        f"Isolated plugin worker timed out after {timeout}s "
                        "(process group terminated)"
                    )
                try:
                    stdout, stderr = proc.communicate(timeout=min(poll, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
    except BaseException:
        # Ensure group is reaped on unexpected errors (cancel/timeout already killed).
        if proc.poll() is None:
            terminate_process_group(pgid)
        raise
    result = subprocess.CompletedProcess(cmd, proc.returncode or 0, stdout, stderr)
    if result.returncode != 0:
        terminate_process_group(pgid)
    return result


def _run_isolated_subprocess_streaming(
    cmd: list[str],
    *,
    env: dict[str, str],
    timeout: float,
    cancel_check: Callable[[], bool] | None,
    cancel_poll_s: float,
    on_progress: Callable[[dict[str, Any]], None],
) -> subprocess.CompletedProcess:
    """Like :func:`_run_isolated_subprocess` but forwards progress lines live."""
    import threading

    from app.core.nodes.progress import parse_progress_line

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
        start_new_session=True,
    )
    pgid = proc.pid
    out_chunks: list[str] = []
    err_lines: list[str] = []

    def _drain_stdout() -> None:
        try:
            for chunk in iter(proc.stdout.readline, ""):
                out_chunks.append(chunk)
        except Exception:
            pass

    def _drain_stderr() -> None:
        try:
            for line in iter(proc.stderr.readline, ""):
                payload = parse_progress_line(line)
                if payload is None:
                    err_lines.append(line)
                    continue
                try:
                    on_progress(payload)
                except Exception:
                    pass
        except Exception:
            pass

    readers = [
        threading.Thread(target=_drain_stdout, daemon=True, name="iso-stdout"),
        threading.Thread(target=_drain_stderr, daemon=True, name="iso-stderr"),
    ]
    for t in readers:
        t.start()

    def _join_readers(limit: float = 8.0) -> None:
        for t in readers:
            t.join(timeout=limit)

    deadline = time.monotonic() + float(timeout)
    poll = max(0.05, float(cancel_poll_s))
    try:
        while True:
            if cancel_check is not None and cancel_check():
                terminate_process_group(pgid)
                _join_readers()
                raise RuntimeError(
                    "cancelled by control plane (isolated process group terminated)"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate_process_group(pgid)
                _join_readers()
                raise RuntimeError(
                    f"Isolated plugin worker timed out after {timeout}s "
                    "(process group terminated)"
                )
            try:
                proc.wait(timeout=min(poll, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        if proc.poll() is None:
            terminate_process_group(pgid)
        raise
    _join_readers()
    result = subprocess.CompletedProcess(
        cmd, proc.returncode or 0, "".join(out_chunks), "".join(err_lines)
    )
    if result.returncode != 0:
        terminate_process_group(pgid)
    return result


# ── Worker failure reporting ─────────────────────────────────────────────────

class IsolatedNodeError(RuntimeError):
    """An isolated plugin worker exited non-zero; carries the *real* exception.

    ``str(exc)`` is ``"<error_type>: <error_message>"`` (or just the type when
    the message is empty) — never the leading TensorFlow/absl stderr noise.
    The full worker traceback and a noise-filtered stderr tail are kept as
    attributes for logs / UI drill-down.
    """

    def __init__(
        self,
        error_type: str,
        error_message: str = "",
        *,
        traceback_text: str = "",
        node_type: str = "",
        plugin_name: str = "",
        exit_code: int | None = None,
        stderr_tail: str = "",
        error_module: str = "",
    ) -> None:
        self.error_type = str(error_type or "WorkerError")
        self.error_message = str(error_message or "")
        self.traceback_text = str(traceback_text or "")
        self.node_type = str(node_type or "")
        self.plugin_name = str(plugin_name or "")
        self.exit_code = exit_code
        self.stderr_tail = str(stderr_tail or "")
        self.error_module = str(error_module or "")
        text = (
            f"{self.error_type}: {self.error_message}"
            if self.error_message
            else self.error_type
        )
        super().__init__(text)

    def __reduce__(self):  # keep picklable despite keyword-only attributes
        return (
            _rebuild_isolated_node_error,
            (
                self.error_type,
                self.error_message,
                self.traceback_text,
                self.node_type,
                self.plugin_name,
                self.exit_code,
                self.stderr_tail,
                self.error_module,
            ),
        )


def _rebuild_isolated_node_error(
    error_type, error_message, traceback_text, node_type, plugin_name,
    exit_code, stderr_tail, error_module,
) -> IsolatedNodeError:
    return IsolatedNodeError(
        error_type,
        error_message,
        traceback_text=traceback_text,
        node_type=node_type,
        plugin_name=plugin_name,
        exit_code=exit_code,
        stderr_tail=stderr_tail,
        error_module=error_module,
    )


# Known ML-runtime stderr noise (TensorFlow / absl / glog / CUDA plugin
# registration). Matched per line; never applied to exception lines.
_STDERR_NOISE = [
    re.compile(r"^WARNING: All log messages before absl::InitializeLog\(\)"),
    re.compile(r"^[IWEF]\d{4} "),
    re.compile(r"oneDNN custom operations"),
    re.compile(r"This TensorFlow binary is optimized"),
    re.compile(r"^To enable the following instructions:"),
    re.compile(r"(?i)\bcuda|\bcudnn|\bcufft|\bcublas|\bcupti"),
    re.compile(r"Unable to register cu"),
    re.compile(r"computation placer already registered"),
    re.compile(r"tensorflow/[\w/.-]+\.cc:\d+\]"),
    re.compile(r"\.cc:\d+\]"),
    re.compile(r"^WARNING: All log messages"),
]
_TRACEBACK_HEADER = "Traceback (most recent call last):"
# Final exception line, e.g. ``ValueError: bad`` / ``pkg.mod.MyError: x`` / ``KeyError``.
_EXC_LINE = re.compile(r"^([A-Za-z_][\w.]*)(?::\s?(.*))?$")
_EXC_NAME_HINT = re.compile(r"(Error|Exception|Exit|Interrupt|Warning|Failure|Fault)$")
_STDERR_TAIL_LINES = 40


def _looks_like_exception_line(line: str) -> bool:
    m = _EXC_LINE.match(line.rstrip())
    if not m:
        return False
    return bool(_EXC_NAME_HINT.search(m.group(1).rsplit(".", 1)[-1]))


def _is_stderr_noise(line: str) -> bool:
    text = line.rstrip("\r\n")
    if not text.strip():
        return True
    if _looks_like_exception_line(text):
        return False
    return any(p.search(text) for p in _STDERR_NOISE)


def _clean_stderr_lines(stderr: str) -> list[str]:
    return [ln.rstrip("\r") for ln in (stderr or "").splitlines() if not _is_stderr_noise(ln)]


def parse_worker_stderr(stderr: str) -> dict[str, str]:
    """Extract the real failure from isolated-worker stderr.

    Returns ``{"error_type", "message", "traceback"}``. Uses the LAST
    ``Traceback (most recent call last):`` block and its final exception line
    (``SomeError: msg``), ignoring TF/absl/glog/CUDA noise. Without a
    traceback, the last non-noise line becomes the message with
    ``error_type="WorkerError"``.
    """
    lines = _clean_stderr_lines(stderr)
    start = None
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].strip() == _TRACEBACK_HEADER:
            start = idx
            break
    if start is not None:
        block = lines[start:]
        exc_idx = None
        for j in range(1, len(block)):
            line = block[j]
            if not line or line[:1].isspace():
                continue  # frame / source / caret lines
            if line.startswith(("During handling", "The above exception")):
                continue
            exc_idx = j
            break
        if exc_idx is not None:
            exc_line = block[exc_idx].strip()
            m = _EXC_LINE.match(exc_line)
            if m:
                name = m.group(1).rsplit(".", 1)[-1]
                message = (m.group(2) or "").strip()
            else:
                name, sep, rest = exc_line.partition(":")
                name = name.strip() or "WorkerError"
                message = rest.strip() if sep else ""
            return {
                "error_type": name,
                "message": message,
                "traceback": "\n".join(block[: exc_idx + 1]),
            }
        return {
            "error_type": "WorkerError",
            "message": "worker traceback without a final exception line",
            "traceback": "\n".join(block),
        }
    message = lines[-1].strip() if lines else ""
    return {"error_type": "WorkerError", "message": message, "traceback": ""}


def _read_worker_error_file(path: Path) -> dict[str, Any] | None:
    """Load the worker's structured ``error.json`` (None when absent/invalid)."""
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("error_type"):
        return None
    return data


def _build_isolated_error(
    result: subprocess.CompletedProcess,
    *,
    error_path: Path,
    node_type: str,
    plugin_name: str,
) -> IsolatedNodeError:
    stderr = result.stderr or ""
    raw = stderr if stderr.strip() else (result.stdout or "")
    tail = "\n".join(_clean_stderr_lines(raw)[-_STDERR_TAIL_LINES:])
    data = _read_worker_error_file(error_path)
    if data is not None:
        error_type = str(data.get("error_type") or "WorkerError")
        message = str(data.get("message") or "")
        tb = str(data.get("traceback") or "")
        module = str(data.get("error_module") or "")
    else:
        parsed = parse_worker_stderr(raw)
        error_type = parsed["error_type"]
        message = parsed["message"]
        tb = parsed["traceback"]
        module = ""
        if not message and error_type == "WorkerError":
            message = f"isolated worker exited with code {result.returncode}"
    return IsolatedNodeError(
        error_type,
        message,
        traceback_text=tb,
        node_type=node_type,
        plugin_name=plugin_name,
        exit_code=result.returncode,
        stderr_tail=tail,
        error_module=module,
    )


def load_isolated_result(path: Path) -> IsolatedResult:
    """Load worker pickle (legacy port-dict or envelope) via RestrictedUnpickler."""
    with path.open("rb") as fh:
        raw = RestrictedUnpickler(fh).load()
    if not isinstance(raw, dict):
        raise RuntimeError(
            f"Isolated worker returned non-dict outputs: {type(raw)}"
        )
    if raw.get(ISOLATED_ENVELOPE_MARK):
        outputs = raw.get("outputs")
        if not isinstance(outputs, dict):
            raise RuntimeError(
                f"Isolated envelope outputs must be a dict, got {type(outputs)}"
            )
        trees_raw = raw.get("published_file_trees") or []
        trees: list[dict[str, Any]] = []
        if isinstance(trees_raw, (list, tuple)):
            for item in trees_raw:
                if isinstance(item, dict) and item.get("root"):
                    trees.append(item)
        return IsolatedResult(outputs=outputs, published_file_trees=tuple(trees))
    return IsolatedResult(outputs=raw, published_file_trees=())


def load_isolated_outputs(path: Path) -> dict[str, Any]:
    """Load worker port outputs only (unwraps envelope when present)."""
    return load_isolated_result(path).outputs


def run_isolated_node(
    spec: IsolatedPluginSpec,
    *,
    node_type: str,
    config: dict[str, Any],
    seed: int,
    inputs: dict[str, Any],
    timeout: float | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> IsolatedResult:
    """Execute *node_type* in the plugin venv worker.

    Returns port outputs plus any ``publish_files`` trees drained in the worker.
    ``cancel_check`` — optional callable polled during the subprocess wait; when
    it returns True the worker process group is terminated (mid-flight cancel).
    """
    from app.core.config import plugin_isolated_timeout

    if timeout is None:
        timeout = plugin_isolated_timeout()

    work = Path(tempfile.mkdtemp(prefix=f"graphyn-iso-{spec.plugin_name}-"))
    inputs_path = work / "inputs.pkl"
    outputs_path = work / "outputs.pkl"
    job_path = work / "job.json"
    error_path = work / "error.json"
    try:
        with inputs_path.open("wb") as fh:
            pickle.dump(
                recast_plugin_types(inputs),
                fh,
                protocol=pickle.HIGHEST_PROTOCOL,
            )

        job = {
            "plugin_dir": spec.install_path,
            "node_type": node_type,
            "config": config,
            "seed": seed,
            "inputs_path": str(inputs_path),
            "outputs_path": str(outputs_path),
            # Worker writes {error_type, error_module, message, traceback} here
            # on failure (app.core.plugins.worker) → IsolatedNodeError.
            "error_path": str(error_path),
        }
        job_path.write_text(json.dumps(job), encoding="utf-8")

        env = os.environ.copy()
        # Ensure the platform source tree is importable inside the worker.
        # Do not inherit user site-packages (would share host TF/Torch).
        project_root = str(Path(__file__).resolve().parents[3])
        prev = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            project_root if not prev else f"{project_root}{os.pathsep}{prev}"
        )
        env["PYTHONNOUSERSITE"] = "1"
        # Inherit host/container NVIDIA libs (LD_LIBRARY_PATH, NVIDIA_*).
        # Do not hide GPUs here; GRAPHYN_TF_DEVICE=cpu is the only path that
        # sets CUDA_VISIBLE_DEVICES=-1 (in configure_tf_stable_defaults).

        # node_progress (app.core.nodes.progress): the worker has no run
        # context, so emit_node_progress() writes ``@@GRAPHYN_PROGRESS@@``
        # stderr lines that are forwarded live to the host sink below.
        from app.core.nodes.progress import PROGRESS_ENV_MARKER, current_progress_sink

        progress_sink = current_progress_sink()
        if progress_sink is not None:
            env[PROGRESS_ENV_MARKER] = "1"
        else:
            env.pop(PROGRESS_ENV_MARKER, None)

        cmd = [
            spec.venv_python,
            "-m",
            "app.core.plugins.worker",
            str(job_path),
        ]
        log.info(
            "Isolated run: plugin=%s node=%s python=%s timeout=%s",
            spec.plugin_name,
            node_type,
            spec.venv_python,
            timeout,
        )
        result = _run_isolated_subprocess(
            cmd,
            env=env,
            timeout=timeout,
            cancel_check=cancel_check,
            on_progress=progress_sink,
        )
        if result.returncode != 0:
            exc = _build_isolated_error(
                result,
                error_path=error_path,
                node_type=node_type,
                plugin_name=spec.plugin_name,
            )
            log.warning(
                "Isolated plugin worker failed for '%s' (plugin=%s, exit=%s): %s\n%s",
                node_type,
                spec.plugin_name,
                result.returncode,
                exc,
                exc.traceback_text or exc.stderr_tail,
            )
            raise exc
        if not outputs_path.exists():
            raise RuntimeError(
                f"Isolated worker for '{node_type}' produced no outputs file"
            )
        return load_isolated_result(outputs_path)
    finally:
        # Best-effort cleanup
        for p in (inputs_path, outputs_path, job_path, error_path):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            work.rmdir()
        except Exception:
            pass
