"""UX overhaul — inspector-facing plugin.toml text.

User-facing ``description`` strings must not leak environment variables,
internal file names or library call names; those live in ``ui.help_advanced``.
Output-location fields sit in the ``Advanced`` group. (toml ↔ Config parity
itself is covered by test_example06_schema.py.)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]
TOMLS = sorted((ROOT / "PluginPackage").glob("*/*/plugin.toml"))

JARGON = [
    r"GRAPHYN_[A-Z_]+", r"CUDA_[A-Z_]+", r"<uuid>", r"X_train_repr", r"tf\.lite", r"tf\.data",
    r"librosa", r"soundfile", r"pyloudnorm", r"isolated-worker", r"metadata\.\w+", r"top_db",
    r"Write under workspace/artifacts",
]
PATH_FIELDS = {"output_path", "output_dir", "checkpoint_path"}


def _fields():
    for path in TOMLS:
        schema = tomllib.loads(path.read_text()).get("config_schema") or {}
        for node, fields in schema.items():
            for key, spec in fields.items():
                if isinstance(spec, dict):
                    yield path, node, key, spec


@pytest.mark.parametrize("path", TOMLS, ids=lambda p: p.parent.name)
def test_descriptions_have_no_jargon(path):
    bad = []
    for p, node, key, spec in _fields():
        if p != path:
            continue
        desc = str(spec.get("description", ""))
        for pat in JARGON:
            if re.search(pat, desc):
                bad.append(f"{node}.{key}: {pat!r} in {desc!r}")
    assert not bad, "\n".join(bad)


def test_output_locations_are_advanced():
    bad = [f"{p.parent.name}:{node}.{key}" for p, node, key, spec in _fields()
           if key in PATH_FIELDS and (spec.get("ui") or {}).get("group") != "Advanced"]
    assert not bad, bad


def test_help_advanced_is_text_and_keeps_the_detail():
    helps = {(node, key): (spec.get("ui") or {}).get("help_advanced") for _p, node, key, spec in _fields()}
    for k, v in helps.items():
        assert v is None or (isinstance(v, str) and v.strip()), k
    device = helps[("trainer", "device")]
    assert "GRAPHYN_TF_DEVICE" in device and "CUDA_VISIBLE_DEVICES" in device
    assert "compiled_<uuid>.keras" in helps[("model_builder", "output_path")]
    assert "X_train_repr.npy" in helps[("edge_optimizer", "representative_samples")]


def test_required_model_path_stays_visible():
    """realtime_inference.model_path is required — keep it out of the Advanced fold."""
    schema = tomllib.loads((ROOT / "PluginPackage/Common/realtime_inference/plugin.toml").read_text())
    spec = schema["config_schema"]["realtime_inference"]["model_path"]
    assert (spec.get("ui") or {}).get("group") != "Advanced"


def test_ui_table_survives_plugin_ui_overlay():
    from app.core.nodes.plugin_ui import json_schema_from_toml_fields

    schema = tomllib.loads((ROOT / "PluginPackage/Common/trainer/plugin.toml").read_text())["config_schema"]["trainer"]
    out = json_schema_from_toml_fields(schema)["properties"]
    assert out["output_path"]["group"] == "Advanced"
    assert "GRAPHYN_TF_DEVICE" in out["device"]["ui"]["help_advanced"]
    assert "GRAPHYN" not in out["device"]["description"]
