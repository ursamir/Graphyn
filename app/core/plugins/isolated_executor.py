# app/core/plugins/isolated_executor.py
"""
Bounded Context:  BC3 / BC5 — Isolated plugin execution bridge
Responsibility:   Run an isolated plugin node's process() in a subprocess
                  using that plugin's venv Python, with pickle IPC via files.
Owns:             run_isolated_node(), recast_plugin_types()
Public Surface:   run_isolated_node, recast_plugin_types, load_isolated_outputs,
                  hydrate_platform_models (via app.core.plugins.hydrate)
Must NOT:         Import from app.domain or app.api.
Dependencies:     stdlib, runtime_registry
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
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.core.plugins.hydrate import coerce_node_inputs, hydrate_platform_models
from app.core.plugins.runtime_registry import IsolatedPluginSpec

__all__ = [
    "RestrictedUnpickler",
    "coerce_node_inputs",
    "hydrate_platform_models",
    "load_isolated_outputs",
    "recast_plugin_types",
    "run_isolated_node",
]

log = logging.getLogger(__name__)

# Host-side unpickle allowlist for worker outputs (fail closed).
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


class RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that refuses globals outside a known port/artifact set."""

    def find_class(self, module: str, name: str) -> Any:
        if module in _ALLOWED_PICKLE_MODULES or module.startswith("app.models."):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(
            f"Refusing to unpickle {module}.{name} from isolated worker output "
            "(not in the host allowlist of builtins/numpy/app.models types)"
        )


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


def _run_isolated_subprocess(
    cmd: list[str],
    *,
    env: dict[str, str],
    timeout: float,
) -> subprocess.CompletedProcess:
    """Run the worker in a new session; terminate the group on timeout/failure.

    Isolated trainer workers can spawn extra Python processes. Killing only
    the leader left leaked ``python -m app.core.plugins.worker`` rows in htop.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    pgid = proc.pid
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_process_group(pgid)
        try:
            stdout, stderr = proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            stdout = stderr = ""
            try:
                proc.kill()
            except Exception:
                pass
        raise RuntimeError(
            f"Isolated plugin worker timed out after {timeout}s "
            "(process group terminated)"
        ) from None
    except BaseException:
        terminate_process_group(pgid)
        raise
    result = subprocess.CompletedProcess(cmd, proc.returncode or 0, stdout, stderr)
    if result.returncode != 0:
        terminate_process_group(pgid)
    return result


def load_isolated_outputs(path: Path) -> dict[str, Any]:
    """Load worker outputs with RestrictedUnpickler; must be a dict."""
    with path.open("rb") as fh:
        outputs = RestrictedUnpickler(fh).load()
    if not isinstance(outputs, dict):
        raise RuntimeError(
            f"Isolated worker returned non-dict outputs: {type(outputs)}"
        )
    return outputs


def run_isolated_node(
    spec: IsolatedPluginSpec,
    *,
    node_type: str,
    config: dict[str, Any],
    seed: int,
    inputs: dict[str, Any],
    timeout: float | None = None,
) -> dict[str, Any]:
    """Execute *node_type* in the plugin venv worker; return process outputs."""
    from app.core.config import plugin_isolated_timeout

    if timeout is None:
        timeout = plugin_isolated_timeout()

    work = Path(tempfile.mkdtemp(prefix=f"graphyn-iso-{spec.plugin_name}-"))
    inputs_path = work / "inputs.pkl"
    outputs_path = work / "outputs.pkl"
    job_path = work / "job.json"
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
        result = _run_isolated_subprocess(cmd, env=env, timeout=timeout)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                f"Isolated plugin worker failed for '{node_type}' "
                f"(plugin={spec.plugin_name}, exit={result.returncode}): {err}"
            )
        if not outputs_path.exists():
            raise RuntimeError(
                f"Isolated worker for '{node_type}' produced no outputs file"
            )
        return load_isolated_outputs(outputs_path)
    finally:
        # Best-effort cleanup
        for p in (inputs_path, outputs_path, job_path):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            work.rmdir()
        except Exception:
            pass
