"""Example 06 — plugin.toml config_schema vs Pydantic Config parity + graph checks.

Covers every plugin used by examples/06_speech_commands_e2e (preprocess, train,
infer). For each ``[config_schema.<node>]`` field we assert:

* the field exists on the node's ``Config`` (and vice versa),
* defaults agree (toml ``default`` vs Pydantic default),
* toml ``enum`` == Pydantic ``Literal`` values,
* toml numeric bounds (minimum/maximum/exclusive*) == Pydantic ge/le/gt/lt,
* ``ui.visible_if`` references real fields with legal values,
* every config key used in the Example 06 graphs is declared and validates.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "PluginPackage"
EX06 = ROOT / "examples" / "06_speech_commands_e2e"

# plugin dir → node types it declares
EX06_PLUGINS: dict[str, list[str]] = {
    "Audio/dataset_ingest": ["dataset_ingest"],
    "Audio/audio_conditioner": ["audio_conditioner"],
    "Audio/segmenter": ["segmenter"],
    "Audio/audio_quality_gate": ["audio_quality_gate"],
    "Audio/augmentation_pipeline": ["augmentation_pipeline"],
    "Audio/audio_exporter": ["audio_exporter"],
    "Audio/feature_frontend": ["feature_frontend"],
    "Common/dataset_builder": ["dataset_builder"],
    "Common/trainer": ["trainer", "model_builder"],
    "Common/evaluator": ["evaluator"],
    "Common/edge_optimizer": ["edge_optimizer"],
    "Common/realtime_inference": ["realtime_inference"],
}

_BOUND_MAP = {
    "minimum": "ge",
    "maximum": "le",
    "exclusiveMinimum": "gt",
    "exclusiveMaximum": "lt",
}


def _load_classes(plugin: str) -> dict[str, type]:
    root = PKG / plugin
    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    for entry in ("types.py", "nodes.py"):
        if (root / entry).is_file():
            disc._process_module(disc._import_file(root / entry, package_prefix=None))
    return {nt: reg.get_class(nt) for nt in EX06_PLUGINS[plugin]}


def _toml(plugin: str) -> dict:
    return tomllib.loads((PKG / plugin / "plugin.toml").read_text())


def _cases():
    for plugin, node_types in EX06_PLUGINS.items():
        for nt in node_types:
            yield pytest.param(plugin, nt, id=nt)


def _pyd_bounds(field) -> dict[str, float]:
    out: dict[str, float] = {}
    for meta in field.metadata:
        for attr in ("ge", "le", "gt", "lt"):
            val = getattr(meta, attr, None)
            if val is not None:
                out[attr] = float(val)
    return out


def _literal_values(annotation) -> list | None:
    import typing

    if typing.get_origin(annotation) is typing.Literal:
        return list(typing.get_args(annotation))
    return None


@pytest.mark.parametrize("plugin,node_type", list(_cases()))
def test_toml_fields_match_config_model(plugin: str, node_type: str) -> None:
    cls = _load_classes(plugin)[node_type]
    fields = cls.Config.model_fields
    schema = _toml(plugin)["config_schema"][node_type]

    toml_keys = set(schema)
    cfg_keys = {k for k in fields if not k.startswith("_")}
    assert toml_keys - cfg_keys == set(), f"declared in toml but not in Config: {toml_keys - cfg_keys}"
    assert cfg_keys - toml_keys == set(), f"in Config but not in toml: {cfg_keys - toml_keys}"

    problems: list[str] = []
    for key, spec in schema.items():
        f = fields[key]
        default = f.default
        if "default" in spec:
            if spec["default"] != default:
                problems.append(f"{key}: default toml={spec['default']!r} Config={default!r}")
        elif default is not None:
            problems.append(f"{key}: toml has no default but Config default={default!r}")
        lit = _literal_values(f.annotation)
        if "enum" in spec or lit is not None:
            if spec.get("enum") != lit:
                problems.append(f"{key}: enum toml={spec.get('enum')} Literal={lit}")
        toml_bounds = {
            _BOUND_MAP[k]: float(v) for k, v in spec.items() if k in _BOUND_MAP
        }
        if toml_bounds != _pyd_bounds(f) and key not in _VALIDATOR_ENFORCED.get(node_type, set()):
            problems.append(f"{key}: bounds toml={toml_bounds} Config={_pyd_bounds(f)}")
    assert not problems, "\n".join(problems)


# Fields whose toml bounds are enforced by a field_validator instead of Field(ge=…).
_VALIDATOR_ENFORCED: dict[str, set[str]] = {
    "audio_conditioner": {"compress_ratio"},
    "segmenter": {"window_ms", "overlap", "vad_aggressiveness", "event_min_gap_ms",
                  "min_segment_ms", "max_segment_ms"},
}


@pytest.mark.parametrize("plugin,node_type", list(_cases()))
def test_validator_enforced_bounds_reject_out_of_range(plugin: str, node_type: str) -> None:
    """toml minimum/maximum/exclusive* must be rejected by Config at the boundary."""
    cls = _load_classes(plugin)[node_type]
    schema = _toml(plugin)["config_schema"][node_type]
    for key, spec in schema.items():
        for bound, op in _BOUND_MAP.items():
            if bound not in spec:
                continue
            limit = spec[bound]
            is_int = spec.get("type") == "integer"
            step = 1 if is_int else 1e-6
            if op in ("ge", "gt"):
                bad = limit - step if op == "ge" else limit
            else:
                bad = limit + step if op == "le" else limit
            if is_int:
                bad = int(bad)
            with pytest.raises(Exception):
                cls.Config(**{key: bad})


@pytest.mark.parametrize("plugin,node_type", list(_cases()))
def test_visible_if_references_valid_fields(plugin: str, node_type: str) -> None:
    schema = _toml(plugin)["config_schema"][node_type]
    for key, spec in schema.items():
        ui = spec.get("ui")
        if not isinstance(ui, dict) or "visible_if" not in ui:
            continue
        cond = ui["visible_if"]
        assert isinstance(cond, dict) and cond, f"{key}: visible_if must be a non-empty table"
        for dep, want in cond.items():
            assert dep in schema, f"{key}: visible_if references unknown field {dep!r}"
            assert dep != key, f"{key}: visible_if references itself"
            values = want if isinstance(want, list) else [want]
            dep_spec = schema[dep]
            for v in values:
                if "enum" in dep_spec:
                    assert v in dep_spec["enum"], f"{key}: {dep}={v!r} not in enum"
                elif dep_spec.get("type") == "boolean":
                    assert isinstance(v, bool), f"{key}: {dep} expects a boolean"


def _ex06_graphs() -> list[Path]:
    return sorted(EX06.glob("*.graph.json"))


@pytest.mark.parametrize("path", _ex06_graphs(), ids=lambda p: p.name)
def test_ex06_graph_config_keys_declared_and_valid(path: Path) -> None:
    graph = json.loads(path.read_text())
    classes: dict[str, type] = {}
    schemas: dict[str, dict] = {}
    for plugin, nts in EX06_PLUGINS.items():
        loaded = _load_classes(plugin)
        for nt in nts:
            classes[nt] = loaded[nt]
            schemas[nt] = _toml(plugin)["config_schema"][nt]
    for node in graph["nodes"]:
        nt = node["node_type"]
        assert nt in classes, f"{path.name}: unknown node type {nt}"
        undeclared = set(node["config"]) - set(schemas[nt])
        assert not undeclared, f"{path.name}:{node['id']} undeclared keys {undeclared}"
        classes[nt].Config(**node["config"])  # validates bounds / enums


def test_preprocess_quality_gates_are_single_purpose() -> None:
    """Gate 3 = quality (SNR...) without duration; gate 4 = duration only.

    Before the fix gate 4 silently re-applied SNR >= 10 dB (the default),
    stricter than gate 3's documented 5 dB.
    """
    for path in sorted(EX06.glob("pipeline_preprocess*.graph.json")):
        nodes = {n["id"]: n["config"] for n in json.loads(path.read_text())["nodes"]}
        g3, g4 = nodes["audio_quality_gate_3"], nodes["audio_quality_gate_4"]
        assert g3["check_duration"] is False and g3["min_snr_db"] == 5.0
        assert g4["check_snr"] is False and g4["check_duration"] is True
        assert not any(g4[k] for k in ("check_clipping", "check_silence", "check_bandwidth"))


def test_preprocess_append_chain() -> None:
    """yes runs first with append=False; the other five labels append."""
    for path in sorted(EX06.glob("pipeline_preprocess*.graph.json")):
        nodes = {n["node_type"]: n["config"] for n in json.loads(path.read_text())["nodes"]}
        expected = path.name == "pipeline_preprocess.graph.json"
        assert nodes["audio_exporter"]["append"] is (not expected)
        assert nodes["audio_exporter"]["version_tag"] == "v1"


def test_train_graph_reads_phase1_dataset() -> None:
    graph = json.loads((EX06 / "pipeline_train_ml.graph.json").read_text())
    ingest = next(n for n in graph["nodes"] if n["node_type"] == "dataset_ingest")["config"]
    exporter = next(
        n for n in json.loads((EX06 / "pipeline_preprocess.graph.json").read_text())["nodes"]
        if n["node_type"] == "audio_exporter"
    )["config"]
    assert ingest["path"] == f"{exporter['output_dir']}/{exporter['version_tag']}"
    assert ingest.get("limit", 0) == 0, "template must not subsample the dataset"
    assert ingest["recursive"] is True


def test_infer_feature_config_matches_training() -> None:
    train = {n["node_type"]: n["config"] for n in json.loads((EX06 / "pipeline_train_ml.graph.json").read_text())["nodes"]}
    infer = {n["node_type"]: n["config"] for n in json.loads((EX06 / "pipeline_infer.graph.json").read_text())["nodes"]}
    for key in ("feature_type", "n_mfcc", "n_fft", "hop_length", "fmax", "normalize"):
        assert infer["feature_frontend"][key] == train["feature_frontend"][key], key
    assert infer["feature_frontend"]["fixed_length"] == train["dataset_builder"]["fixed_length"] == 101
