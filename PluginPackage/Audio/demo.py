#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)

if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

_RESET = "\033[0m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_DIM = "\033[2m"
_YELLOW = "\033[33m"


def _h(text: str) -> str:
    return f"{_BOLD}{_CYAN}{text}{_RESET}"


def _ok(text: str) -> str:
    return f"{_GREEN}{text}{_RESET}"


def _dim(text: str) -> str:
    return f"{_DIM}{text}{_RESET}"


def _warn(text: str) -> str:
    return f"{_YELLOW}{text}{_RESET}"


EXAMPLE_DIR = Path(__file__).parent
INPUT_DIR = EXAMPLE_DIR / "input"

from app.core.plugins.manager import PluginManager
from app.core.registry_runtime import get_registry
from app.core.sdk import Pipeline, PipelineNode


def show_manifest(plugin_dir: Path) -> None:
    manifest_path = plugin_dir / "plugin.toml"

    print(f"\n{_h('plugin.toml')}")
    print(f"  path: {manifest_path}")
    print(f"  {_dim('─' * 60)}")

    with open(manifest_path, "r") as f:
        for line in f:
            print(f"  {_dim(line.rstrip())}")


def install_plugin(manager: PluginManager, plugin_dir: Path) -> None:
    print(f"\n{_h('Install Plugin')}")

    record = manager.install(
        str(plugin_dir),
        upgrade=True,
    )

    print(
        f"  {_ok('✓')} Installed: "
        f"{_BOLD}{record.name}{_RESET} "
        f"v{record.version}"
    )

    print(f"    enabled:      {record.enabled}")
    print(f"    install_path: {_dim(record.install_path)}")


def show_registry_info(node_name: str) -> None:
    registry = get_registry()

    if node_name not in registry:
        print(
            f"  {_warn('⚠')} "
            f"{node_name} not found in registry"
        )
        return

    meta = registry.get_metadata(node_name)

    print(f"\n{_h('Metadata')}")
    print(f"  label:       {meta.label}")
    print(f"  category:    {meta.category}")
    print(f"  version:     {meta.version}")
    print(f"  description: {meta.description}")
    print(f"  tags:        {meta.tags}")

    print(f"\n{_h('Capabilities')}")
    print(f"  supports_cpu:      {meta.supports_cpu}")
    print(f"  supports_edge:     {meta.supports_edge}")
    print(f"  deterministic:     {meta.deterministic}")
    print(f"  cacheable:         {meta.cacheable}")
    print(f"  streaming_support: {meta.streaming_support}")
    print(f"  realtime_support:  {meta.realtime_support}")

    print(f"\n{_h('Ports')}")
    print("\n  Input Ports:")

    for port_name in meta.input_ports.keys():
        print(f"    • {port_name}")

    print("\n  Output Ports:")

    for port_name in meta.output_ports.keys():
        print(f"    • {port_name}")

    print(f"\n{_h('Config Schema')}")

    schema = registry.get_config_schema(node_name)
    properties = schema.get("properties", {})

    for field_name, field_info in properties.items():
        field_type = field_info.get("type", "unknown")
        default = field_info.get("default", "<required>")

        print(
            f"    • {field_name:<24} "
            f"type={field_type:<10} "
            f"default={default}"
        )


def validate_input_audio() -> bool:
    if not INPUT_DIR.exists():
        print(
            f"  {_warn('⚠')} "
            f"Input directory not found:"
        )

        print(f"    {INPUT_DIR}")
        return False

    audio_files = []

    for ext in ["*.wav", "*.mp3", "*.ogg", "*.m4a"]:
        audio_files.extend(INPUT_DIR.glob(ext))

    if not audio_files:
        print(
            f"  {_warn('⚠')} "
            f"No audio files found in:"
        )

        print(f"    {INPUT_DIR}")
        return False

    print(f"\n  Found {len(audio_files)} audio file(s):")

    for f in audio_files:
        print(f"    • {f.name}")

    return True


def demo_audio_conditioner() -> None:
    print(f"\n{'=' * 70}")
    print(_h("Audio Conditioner Plugin"))
    print(f"{'=' * 70}")

    plugin_dir = EXAMPLE_DIR / "audio_conditioner"

    show_manifest(plugin_dir)

    manager = PluginManager()

    # Install dataset_ingest so the "dataset_ingest" node_type is available
    install_plugin(manager, EXAMPLE_DIR / "dataset_ingest")
    install_plugin(manager, plugin_dir)

    manager.load_enabled_plugins()

    show_registry_info("audio_conditioner")

    print(f"\n{_h('Run Pipeline')}")

    if not validate_input_audio():
        return

    output_dir = (
        EXAMPLE_DIR
        / "output"
        / "audio_conditioner_demo"
    )

    pipeline = Pipeline(
        nodes=[
            PipelineNode(
                "dataset_ingest",
                {
                    "path": str(INPUT_DIR),
                },
            ),
            PipelineNode(
                "audio_conditioner",
                {
                    "target_sample_rate": 16000,
                    "mono": True,
                    "trim_silence": True,
                    "trim_threshold_db": 40.0,
                    "normalize": True,
                    "normalize_method": "peak",
                    "target_level_db": -1.0,
                    "remove_dc_offset": True,
                    "preemphasis": False,
                    "preemphasis_coeff": 0.97,
                    "limiter": True,
                    "skip_clipped": False,
                },
            ),
            PipelineNode(
                "split",
                {},
            ),
            PipelineNode(
                "file_export",
                {
                    "output": str(output_dir),
                    "project": "audio_conditioner_demo",
                    "version": "v1",
                    "append": True,
                },
            ),
        ],
        name="audio-conditioner-demo",
        description="Audio conditioner plugin demo",
        seed=42,
    )

    try:
        pipeline.run(use_cache=False)

        print(
            f"\n  {_ok('✓')} "
            f"Pipeline completed"
        )

        exported = list(output_dir.rglob("*"))

        print(f"\n{_h('Exported Files')}")
        print(f"  total_files: {len(exported)}")

        for file in exported[:10]:
            if file.is_file():
                print(f"    • {file}")

    except Exception as exc:
        print(
            f"\n  {_warn('⚠')} "
            f"Pipeline execution failed:"
        )

        print(f"    {exc}")


def demo_feature_frontend() -> None:
    print(f"\n{'=' * 70}")
    print(_h("Feature Frontend Plugin"))
    print(f"{'=' * 70}")

    plugin_dir = EXAMPLE_DIR / "feature_frontend"

    show_manifest(plugin_dir)

    manager = PluginManager()

    # Install dataset_ingest so the "dataset_ingest" node_type is available
    install_plugin(manager, EXAMPLE_DIR / "dataset_ingest")
    install_plugin(manager, EXAMPLE_DIR / "audio_conditioner")
    install_plugin(manager, plugin_dir)

    manager.load_enabled_plugins()

    show_registry_info("feature_frontend")

    print(f"\n{_h('Run Pipeline')}")

    if not validate_input_audio():
        return

    pipeline = Pipeline(
        nodes=[
            PipelineNode(
                "dataset_ingest",
                {
                    "path": str(INPUT_DIR),
                },
            ),
            PipelineNode(
                "audio_conditioner",
                {
                    "target_sample_rate": 16000,
                    "mono": True,
                    "normalize": True,
                },
            ),
            PipelineNode(
                "feature_frontend",
                {
                    "feature_type": "log_mel",
                    "sample_rate": 16000,
                    "n_fft": 512,
                    "hop_length": 160,
                    "win_length": 400,
                    "n_mels": 80,
                    "normalize": True,
                },
            ),
        ],
        name="feature-frontend-demo",
        description="Feature frontend plugin demo",
        seed=42,
    )

    try:
        outputs = pipeline.run(use_cache=False)

        print(
            f"\n  {_ok('✓')} "
            f"Pipeline completed"
        )

        feature_outputs = None

        for value in outputs.values():
            if (
                isinstance(value, list)
                and len(value) > 0
            ):
                feature_outputs = value

        if feature_outputs:
            print(
                f"\n{_h('Extracted Features')} "
                f"({len(feature_outputs)})"
            )

            for idx, feat in enumerate(feature_outputs[:3]):

                print(f"\n  [{idx}]")

                feature_type = feat.feature_type or feat.metadata.get(
                    "feature_type",
                    "unknown",
                )

                sample_rate = feat.sample_rate

                print(f"    feature_type: {feature_type}")
                print(f"    shape:        {feat.data.shape}")
                print(f"    dtype:        {feat.data.dtype}")
                print(f"    sample_rate:  {sample_rate}")

                print("    metadata:")

                for k, v in feat.metadata.items():
                    print(f"      {k}: {v}")
    except Exception as exc:
        print(
            f"\n  {_warn('⚠')} "
            f"Pipeline execution failed:"
        )

        print(f"    {exc}")


def main() -> None:
    demo_audio_conditioner()

    demo_feature_frontend()

    # print(f"\n{'=' * 70}")
    # print(_h("CLI Examples"))
    # print(f"{'=' * 70}")

    # print("\n  graphyn plugin install audio_conditioner")
    # print("  graphyn plugin install feature_frontend")
    # print("  graphyn plugin list")
    # print("  graphyn plugin info audio_conditioner")
    # print("  graphyn plugin info feature_frontend")
    # print("  graphyn plugin disable audio_conditioner")
    # print("  graphyn plugin enable audio_conditioner")

    print(f"\n{'=' * 70}\n")


if __name__ == "__main__":
    main()