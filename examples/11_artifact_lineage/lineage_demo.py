#!/usr/bin/env python3
"""
Example 11 — Artifact Lineage Tracking (Priority 5 — B1)
=========================================================
Demonstrates Phase 4 provenance: artifact tracking, lineage trees,
and the ArtifactCollection returned by Pipeline.run().

What this shows:
  - result.artifacts          — list[ArtifactRecord] from Pipeline.run()
  - result.run_id             — run ID from ArtifactCollection
  - result.get_by_type(...)   — filter artifacts by type
  - result.lineage(id)        — full upstream provenance tree
  - ArtifactStore.list(...)   — query artifacts by run/node/type
  - ProvenanceStore.get_lineage() — recursive lineage tree
  - graphyn artifacts list --run <run_id>
  - graphyn artifacts lineage <artifact_id>
  - GET /api/v1/artifacts/{id}/lineage

Usage:
  venv/bin/python examples/11_artifact_lineage/lineage_demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from app.core.sdk import Pipeline, PipelineNode  # noqa: E402
from app.core.plugins.manager import PluginManager  # noqa: E402

# ── Install required plugins ──────────────────────────────────────────────────
_manager = PluginManager()
_manager.install("PluginPackage/Audio/dataset_ingest/")
_manager.install("PluginPackage/Audio/audio_conditioner/")
_manager.install("PluginPackage/Audio/segmenter/")
_manager.install("PluginPackage/Audio/audio_quality_gate/")
_manager.install("PluginPackage/Audio/feature_frontend/")
_manager.install("PluginPackage/Common/dataset_builder/")
_manager.install("PluginPackage/Common/dataset_versioner/")
_manager.load_enabled_plugins()

_RESET = "\033[0m"; _BOLD = "\033[1m"; _CYAN = "\033[36m"
_GREEN = "\033[32m"; _DIM = "\033[2m"; _YELLOW = "\033[33m"
def _h(t): return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t): return f"{_GREEN}{t}{_RESET}"
def _dim(t): return f"{_DIM}{t}{_RESET}"

EXAMPLE_DIR = Path(__file__).parent
DATA_PATH   = Path(WORKSPACE_ROOT) / "examples" / "02_speech_commands" / "data" / "yes"
OUTPUT_DIR  = EXAMPLE_DIR / "output"


def print_lineage_tree(node: dict, indent: int = 0) -> None:
    """Recursively print a lineage tree."""
    prefix = "  " * indent
    aid    = node.get("artifact_id", "?")[:8]
    ntype  = node.get("node_type", "?")
    nid    = node.get("node_id", "?")
    err    = node.get("error")
    if err:
        print(f"{prefix}{_dim('└─')} {_dim(aid)} [{_dim(err)}]")
    else:
        marker = "└─" if indent > 0 else "◉"
        print(f"{prefix}{_dim(marker)} {_BOLD}{ntype}{_RESET} "
              f"{_dim('(' + nid + ')')}  artifact: {_dim(aid + '...')}")
    for inp in node.get("inputs", []):
        print_lineage_tree(inp, indent + 1)


def main() -> None:
    if not DATA_PATH.exists():
        print(f"Missing data: {DATA_PATH}")
        print("Run: venv/bin/python examples/prepare_real_data.py")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(_h("Example 11 — Artifact Lineage Tracking"))
    print(f"{'='*60}")

    # ── Run pipeline ──────────────────────────────────────────────────
    print(f"\n{_h('Step 1 — Run pipeline and collect ArtifactCollection')}")
    pipeline = Pipeline(
        nodes=[
            PipelineNode("dataset_ingest",    {"path": str(DATA_PATH), "recursive": False, "source_type": "filesystem"}),
            PipelineNode("audio_conditioner", {"target_sample_rate": 16000}),
            PipelineNode("segmenter",         {"silence_threshold_db": 40.0, "mode": "silence"}),
            PipelineNode("audio_quality_gate",{"min_snr_db": 5.0}),
            PipelineNode("feature_frontend", {
                "feature_type": "mfcc",
                "n_mfcc": 40,
                "n_fft": 512,
                "hop_length": 160,
                "fmax": 8000.0,
            }),
            PipelineNode("dataset_builder",   {"split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15}, "fixed_length": 101}),
            PipelineNode("dataset_versioner", {
                "output_dir": str(OUTPUT_DIR), "version_tag": "v1",
            }),
        ],
        seed=42,
    )

    result = pipeline.run(use_cache=False)

    print(f"  {_ok('✓')} Pipeline completed")
    print(f"    run_id:    {_BOLD}{result.run_id}{_RESET}")
    print(f"    artifacts: {len(result.artifacts)}")

    # ── ArtifactCollection API ────────────────────────────────────────
    print(f"\n{_h('Step 2 — Inspect ArtifactCollection')}")
    print(f"  result.run_id = {result.run_id}")
    print(f"  result.artifacts ({len(result.artifacts)} records):")
    for rec in result.artifacts:
        print(f"    {_ok('•')} {_BOLD}{rec.artifact_type:<20}{_RESET} "
              f"node={_dim(rec.node_id)}  id={_dim(rec.artifact_id)}")

    audio_artifacts = result.get_by_type("audio_samples")
    print(f"\n  result.get_by_type('audio_samples') → {len(audio_artifacts)} records")

    # ── ArtifactStore query ───────────────────────────────────────────
    print(f"\n{_h('Step 3 — Query ArtifactStore')}")
    from app.core.artifact_store import ArtifactStore
    store = ArtifactStore()

    all_artifacts = store.list(run_id=result.run_id)
    print(f"  store.list(run_id='{result.run_id[:8]}...') → {len(all_artifacts)} records")
    for rec in all_artifacts:
        print(f"    {_dim(rec.artifact_id)} {rec.artifact_type:<20} "
              f"node={_dim(rec.node_id)}  hash={_dim(rec.content_hash[:12] + '...')}")

    # ── Lineage tree ──────────────────────────────────────────────────
    print(f"\n{_h('Step 4 — Walk lineage tree')}")
    from app.core.provenance import ProvenanceStore
    prov_store = ProvenanceStore()

    # Find the last artifact (deepest in the pipeline)
    if result.artifacts:
        last_artifact = result.artifacts[-1]  # last in execution order = deepest lineage
        print(f"  Tracing lineage for artifact: {_BOLD}{last_artifact.artifact_id}{_RESET}")
        print(f"  (node: {last_artifact.node_type}, type: {last_artifact.artifact_type})")
        print()

        lineage = prov_store.get_lineage(last_artifact.artifact_id)
        print_lineage_tree(lineage)

        # Also show via ArtifactCollection.lineage()
        print(f"\n  result.lineage('{last_artifact.artifact_id}') — same tree via SDK:")
        lineage2 = result.lineage(last_artifact.artifact_id)
        depth = lambda n: 1 + max((depth(i) for i in n.get("inputs", [])), default=0)
        print(f"    Tree depth: {depth(lineage2)}")
        print(f"    Root node:  {lineage2.get('node_type', '?')}")

    # ── CLI commands ──────────────────────────────────────────────────
    print(f"\n{_h('Step 5 — Equivalent CLI commands')}")
    print(f"  # List artifacts for this run:")
    print(f"  graphyn artifacts list --run {result.run_id}")
    if result.artifacts:
        aid = result.artifacts[0].artifact_id
        print(f"\n  # Get lineage tree:")
        print(f"  graphyn artifacts lineage {aid}")
        print(f"\n  # REST API:")
        print(f"  curl http://localhost:8001/api/v1/artifacts/{aid}/lineage")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
