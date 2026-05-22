# unit_test/core/ir/test_ir_migrate.py
"""Tests for app/core/ir/migrate.py — Req 19 criteria 23–25."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.ir.migrate import migrate_yaml_to_ir_file
from app.core.ir.loader import load_ir_from_file


# ── Helpers ───────────────────────────────────────────────────────────────────

_MINIMAL_YAML = """\
pipeline:
  name: test_pipeline
  seed: 42
  nodes:
    - type: audio_conditioner
      id: node_a
    - type: feature_frontend
      id: node_b
"""

_SINGLE_NODE_YAML = """\
pipeline:
  name: single
  seed: 0
  nodes:
    - type: audio_conditioner
"""


def _write_yaml(tmp_path: Path, content: str, filename: str = "pipeline.yaml") -> Path:
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


# ── Req 19.23: writes .graph.json next to YAML and returns its path ───────────

class TestMigrateDefaultOutput:
    def test_returns_path_string(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        result = migrate_yaml_to_ir_file(str(yaml_path))
        assert isinstance(result, str)

    def test_output_file_exists(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        result = migrate_yaml_to_ir_file(str(yaml_path))
        assert Path(result).exists()

    def test_output_is_next_to_yaml(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        result = migrate_yaml_to_ir_file(str(yaml_path))
        assert Path(result).parent == tmp_path

    def test_output_has_graph_json_extension(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        result = migrate_yaml_to_ir_file(str(yaml_path))
        assert result.endswith(".graph.json")

    def test_stem_matches_yaml_stem(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML, "my_pipeline.yaml")
        result = migrate_yaml_to_ir_file(str(yaml_path))
        assert Path(result).name == "my_pipeline.graph.json"

    def test_yml_extension_also_works(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML, "pipeline.yml")
        result = migrate_yaml_to_ir_file(str(yaml_path))
        assert result.endswith(".graph.json")
        assert Path(result).exists()


# ── Req 19.24: custom output_path is respected ────────────────────────────────

class TestMigrateCustomOutput:
    def test_custom_path_is_used(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        custom = str(tmp_path / "custom.graph.json")
        result = migrate_yaml_to_ir_file(str(yaml_path), output_path=custom)
        assert result == custom

    def test_custom_path_file_exists(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        custom = str(tmp_path / "custom.graph.json")
        migrate_yaml_to_ir_file(str(yaml_path), output_path=custom)
        assert Path(custom).exists()

    def test_custom_path_in_subdirectory(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        subdir = tmp_path / "output"
        subdir.mkdir()
        custom = str(subdir / "result.graph.json")
        result = migrate_yaml_to_ir_file(str(yaml_path), output_path=custom)
        assert Path(result).exists()
        assert Path(result).parent == subdir

    def test_custom_path_returned_matches_argument(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        custom = str(tmp_path / "out.graph.json")
        result = migrate_yaml_to_ir_file(str(yaml_path), output_path=custom)
        assert result == custom


# ── Req 19.25: written .graph.json is valid IR JSON ──────────────────────────

class TestMigrateOutputIsValidIR:
    def test_output_parseable_by_load_ir_from_file(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        result = migrate_yaml_to_ir_file(str(yaml_path))
        # Should not raise
        graph = load_ir_from_file(result)
        assert graph is not None

    def test_output_has_correct_node_count(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        result = migrate_yaml_to_ir_file(str(yaml_path))
        graph = load_ir_from_file(result)
        assert len(graph.nodes) == 2

    def test_output_preserves_seed(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        result = migrate_yaml_to_ir_file(str(yaml_path))
        graph = load_ir_from_file(result)
        assert graph.metadata.seed == 42

    def test_output_preserves_name(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        result = migrate_yaml_to_ir_file(str(yaml_path))
        graph = load_ir_from_file(result)
        assert graph.metadata.name == "test_pipeline"

    def test_single_node_yaml_produces_valid_ir(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _SINGLE_NODE_YAML)
        result = migrate_yaml_to_ir_file(str(yaml_path))
        graph = load_ir_from_file(result)
        assert len(graph.nodes) == 1

    def test_custom_output_also_valid_ir(self, tmp_path: Path):
        yaml_path = _write_yaml(tmp_path, _MINIMAL_YAML)
        custom = str(tmp_path / "custom.graph.json")
        migrate_yaml_to_ir_file(str(yaml_path), output_path=custom)
        graph = load_ir_from_file(custom)
        assert len(graph.nodes) == 2
