# app/core/plugins/worker.py
"""
Bounded Context:  BC3 — Node Catalog (Plugin Ecosystem)
Responsibility:   Subprocess entry point that loads one plugin node and runs
                  process() for isolated runtimes.
Owns:             main() CLI for ``python -m app.core.plugins.worker``
Public Surface:   main
Must NOT:         Import from app.api.
Dependencies:     stdlib, plugin loader pieces, NodeRegistry
Reason To Change: Job JSON schema or worker bootstrap changes.
"""

from __future__ import annotations

import json
import pickle
import sys
import traceback
from pathlib import Path
from typing import Any


def _load_job(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run(job: dict[str, Any]) -> None:
    # Before pickle.load / plugin imports that pull in TensorFlow.
    from app.core.tf_runtime import configure_tf_stable_defaults

    configure_tf_stable_defaults()

    from app.core.nodes.discovery import AutoDiscovery
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manifest import load_manifest

    plugin_dir = Path(job["plugin_dir"])
    node_type = job["node_type"]
    config = job.get("config") or {}
    seed = int(job.get("seed") or 42)
    inputs_path = Path(job["inputs_path"])
    outputs_path = Path(job["outputs_path"])

    with inputs_path.open("rb") as fh:
        inputs = pickle.load(fh)

    from app.core.plugins.hydrate import coerce_node_inputs

    registry = NodeRegistry()
    discovery = AutoDiscovery(registry)
    manifest = load_manifest(plugin_dir)
    for ep in manifest.entry_points:
        ep_path = plugin_dir / ep
        module = discovery._import_file(ep_path, package_prefix=None)  # noqa: SLF001
        discovery._process_module(module)  # noqa: SLF001

    node_cls = registry.get_class(node_type)
    inputs = coerce_node_inputs(inputs, node_cls)
    node = node_cls(config=config, seed=seed)
    from app.core.write_paths import ensure_node_write_dirs

    ensure_node_write_dirs(node)
    node.setup()
    try:
        outputs = node.process(inputs) or {}
    finally:
        try:
            node.teardown()
        except Exception:
            pass

    with outputs_path.open("wb") as fh:
        pickle.dump(outputs, fh, protocol=pickle.HIGHEST_PROTOCOL)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m app.core.plugins.worker <job.json>", file=sys.stderr)
        return 2
    job_path = Path(argv[0])
    try:
        job = _load_job(job_path)
        _run(job)
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
