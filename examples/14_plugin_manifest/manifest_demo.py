#!/usr/bin/env python3
"""
Example 14 — Plugin Manifest and Versioning (Priority 8 — C1)
==============================================================
Demonstrates the full Phase 5 plugin lifecycle using a plugin.toml manifest.

What this shows:
  - plugin.toml manifest structure (name, version, entry_points, platform_version)
  - PluginManager.install() — local directory install
  - PluginManager.list_installed() — list with version and status
  - PluginManager.enable() / disable() — hot toggle
  - PluginStore — JSON-backed registry in workspace/plugins/
  - AutoDiscovery loading manifested plugins
  - Using a manifested plugin in a pipeline

Usage:
  venv/bin/python examples/14_plugin_manifest/manifest_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar

WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

_RESET = "\033[0m"; _BOLD = "\033[1m"; _CYAN = "\033[36m"
_GREEN = "\033[32m"; _DIM = "\033[2m"; _YELLOW = "\033[33m"
def _h(t): return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t): return f"{_GREEN}{t}{_RESET}"
def _dim(t): return f"{_DIM}{t}{_RESET}"
def _warn(t): return f"{_YELLOW}{t}{_RESET}"

EXAMPLE_DIR = Path(__file__).parent
PLUGIN_DIR  = EXAMPLE_DIR / "text_stats_plugin"


def main() -> None:
    print(f"\n{'='*60}")
    print(_h("Example 14 — Plugin Manifest and Versioning"))
    print(f"{'='*60}")

    # ── Show manifest ─────────────────────────────────────────────────
    print(f"\n{_h('Step 0 — plugin.toml manifest')}")
    manifest_path = PLUGIN_DIR / "plugin.toml"
    print(f"  {manifest_path}")
    print(f"  {_dim('─'*50)}")
    with open(manifest_path) as f:
        for line in f:
            print(f"  {_dim(line.rstrip())}")

    # ── Step 1: Install plugin ────────────────────────────────────────
    print(f"\n{_h('Step 1 — Install plugin from local directory')}")
    print(f"  Source: {PLUGIN_DIR}")

    from app.core.plugins.manager import PluginManager
    manager = PluginManager()

    try:
        record = manager.install(str(PLUGIN_DIR), upgrade=True)
        print(f"  {_ok('✓')} Installed: {_BOLD}{record.name}{_RESET} v{record.version}")
        print(f"    enabled:     {record.enabled}")
        print(f"    install_path:{_dim(record.install_path)}")
    except Exception as exc:
        print(f"  {_warn('⚠')} Install error: {exc}")

    # ── Step 2: List installed plugins ────────────────────────────────
    print(f"\n{_h('Step 2 — List installed plugins')}")
    installed = manager.list_installed()
    print(f"  {len(installed)} plugin(s) installed:")
    for p in installed:
        status = _ok("enabled") if p.enabled else _warn("disabled")
        manifest = p.manifest or {}
        node_types = manifest.get("node_types", [])
        print(f"    {_BOLD}{p.name:<20}{_RESET} v{p.version}  [{status}]  "
              f"source: {_dim(p.source[:30] + '...' if len(p.source) > 30 else p.source)}")

    # ── Step 3: Load and use in pipeline ─────────────────────────────
    print(f"\n{_h('Step 3 — Load plugin and use in pipeline')}")
    manager.load_enabled_plugins()

    from app.core.registry_runtime import get_registry
    registry = get_registry()

    if "text_stats" in registry:
        print(f"  {_ok('✓')} text_stats node registered")
        meta = registry.get_metadata("text_stats")
        print(f"    label:    {meta.label}")
        print(f"    category: {meta.category}")
        print(f"    version:  {meta.version}")
        print(f"    tags:     {meta.tags}")
    else:
        print(f"  {_warn('⚠')} text_stats not in registry")

    # Build a pipeline using the plugin node
    from app.core.nodes.base import Node
    from app.core.nodes.config import NodeConfig
    from app.core.nodes.metadata import NodeMetadata
    from app.core.nodes.ports import InputPort, OutputPort
    from app.models.data_sample import DataSample

    class TextSourceNode(Node):
        node_type: ClassVar[str] = "_text_source_14"
        metadata: ClassVar[NodeMetadata] = NodeMetadata(
            node_type="_text_source_14", label="Text Source",
            description="Emits sample text DataSamples.", category="Test",
        )
        input_ports:  ClassVar[dict] = {}
        output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
        class Config(NodeConfig): pass
        def process(self, inputs: dict) -> dict:
            texts = [
                "Hello world. This is a test sentence! How are you?",
                "The quick brown fox jumps over the lazy dog.",
                "Python is great for data processing. It is fast and readable.",
            ]
            return {"output": [DataSample(id=str(i), source=t) for i, t in enumerate(texts)]}

    if "_text_source_14" not in registry:
        registry.register("_text_source_14", TextSourceNode, TextSourceNode.metadata)

    from app.core.sdk import Pipeline, PipelineNode
    pipeline = Pipeline(
        nodes=[
            PipelineNode("_text_source_14", {}),
            PipelineNode("text_stats", {"add_word_count": True,
                                         "add_char_count": True,
                                         "add_sentence_count": True}),
        ],
        seed=42,
    )
    result = pipeline.run(use_cache=False)
    print(f"\n  {_ok('✓')} Pipeline with plugin node completed — run_id: {result.run_id}")

    # ── Step 4: Disable / re-enable ───────────────────────────────────
    print(f"\n{_h('Step 4 — Disable and re-enable plugin')}")
    try:
        rec = manager.disable("text-stats")
        print(f"  {_ok('✓')} Disabled:    {rec.name}  enabled={rec.enabled}")
        rec = manager.enable("text-stats")
        print(f"  {_ok('✓')} Re-enabled:  {rec.name}  enabled={rec.enabled}")
    except Exception as exc:
        print(f"  {_warn('⚠')} {exc}")

    # ── Step 5: Inspect via get() ─────────────────────────────────────
    print(f"\n{_h('Step 5 — Inspect plugin record')}")
    try:
        rec = manager.get("text-stats")
        print(f"  name:         {rec.name}")
        print(f"  version:      {rec.version}")
        print(f"  enabled:      {rec.enabled}")
        print(f"  install_path: {_dim(rec.install_path)}")
    except Exception as exc:
        print(f"  {_warn('⚠')} {exc}")

    print(f"\n{_h('CLI equivalents')}")
    print(f"  graphyn plugin install {PLUGIN_DIR}")
    print(f"  graphyn plugin list")
    print(f"  graphyn plugin disable text-stats")
    print(f"  graphyn plugin enable text-stats")
    print(f"  graphyn plugin info text-stats")
    print(f"  graphyn plugin remove text-stats")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
