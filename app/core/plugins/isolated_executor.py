# app/core/plugins/isolated_executor.py
"""
Bounded Context:  BC3 / BC5 — Isolated plugin execution bridge
Responsibility:   Run an isolated plugin node's process() in a subprocess
                  using that plugin's venv Python, with pickle IPC via files.
Owns:             run_isolated_node()
Public Surface:   run_isolated_node
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
Override worker timeout with GRAPHYN_PLUGIN_ISOLATED_TIMEOUT (seconds).
Default: 3600.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.core.plugins.runtime_registry import IsolatedPluginSpec

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
            pickle.dump(inputs, fh, protocol=pickle.HIGHEST_PROTOCOL)

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
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
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
