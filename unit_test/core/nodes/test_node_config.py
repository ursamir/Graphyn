# unit_test/core/nodes/test_node_config.py
"""Tests for app/core/nodes/config.py — Req 18 criteria 9–10."""
from __future__ import annotations

import pytest
import pydantic

from app.core.nodes.config import NodeConfig


class _AllDefaultConfig(NodeConfig):
    """A NodeConfig subclass with all-default fields."""
    sample_rate: int = 16000
    mono: bool = True


class _ForbidConfig(NodeConfig):
    """NodeConfig with extra='forbid' (inherited from NodeConfig base)."""
    value: int = 0


class TestNodeConfigExtraForbid:
    """Req 18.9 — unknown fields raise pydantic.ValidationError."""

    def test_unknown_field_raises_validation_error(self):
        """Req 18.9: extra='forbid' raises ValidationError for unknown fields."""
        with pytest.raises(pydantic.ValidationError):
            _ForbidConfig.model_validate({"value": 1, "unknown_field": "bad"})

    def test_unknown_field_on_base_raises_validation_error(self):
        """NodeConfig base itself also forbids extra fields."""
        with pytest.raises(pydantic.ValidationError):
            NodeConfig.model_validate({"unexpected": True})


class TestNodeConfigModelValidate:
    """Req 18.10 — model_validate({}) succeeds for all-default config."""

    def test_model_validate_empty_dict_succeeds(self):
        """Req 18.10: model_validate({}) succeeds for config with all-default fields."""
        config = _AllDefaultConfig.model_validate({})
        assert config.sample_rate == 16000
        assert config.mono is True

    def test_model_validate_with_valid_fields_succeeds(self):
        config = _AllDefaultConfig.model_validate({"sample_rate": 8000})
        assert config.sample_rate == 8000

    def test_base_node_config_model_validate_empty_succeeds(self):
        """NodeConfig base with no fields accepts empty dict."""
        config = NodeConfig.model_validate({})
        assert config is not None

    def test_round_trip_via_model_dump(self):
        """Config round-trips through model_dump and model_validate."""
        original = _AllDefaultConfig(sample_rate=22050, mono=False)
        dumped = original.model_dump()
        restored = _AllDefaultConfig.model_validate(dumped)
        assert restored.sample_rate == 22050
        assert restored.mono is False


class _TrainerLikeConfig(NodeConfig):
    """Mirrors trainer: output_path only — no project / output_dir."""
    output_path: str = "workspace/artifacts/models"
    epochs: int = 1


class TestSanitizeStampKeys:
    """Legacy UI stamps must not fail Config validation (extra=forbid)."""

    def test_sanitize_strips_project_and_output_dir(self):
        from app.core.nodes.config import sanitize_node_config_dict

        raw = {
            "output_path": "workspace/artifacts/speech-commands",
            "epochs": 2,
            "project": "r2",
            "output_dir": "/workspace/datasets/output/r2",
            "version_tag": "v1",
        }
        cleaned = sanitize_node_config_dict(_TrainerLikeConfig, raw)
        assert "project" not in cleaned
        assert "output_dir" not in cleaned
        assert "version_tag" not in cleaned
        assert cleaned["output_path"] == "workspace/artifacts/speech-commands"
        cfg = _TrainerLikeConfig.model_validate(cleaned)
        assert cfg.epochs == 2

    def test_sanitize_maps_output_dir_to_output_path_when_missing(self):
        from app.core.nodes.config import sanitize_node_config_dict

        raw = {"project": "r2", "output_dir": "workspace/artifacts/models/r2"}
        cleaned = sanitize_node_config_dict(_TrainerLikeConfig, raw)
        assert cleaned["output_path"] == "workspace/artifacts/models/r2"
        assert "output_dir" not in cleaned
        assert "project" not in cleaned

    def test_node_init_accepts_stamped_extras(self):
        from typing import ClassVar

        from app.core.nodes.base import Node
        from app.core.nodes.metadata import NodeMetadata
        from app.core.nodes.ports import InputPort, OutputPort

        class _Trainerish(Node):
            node_type: ClassVar[str] = "_test_trainerish"
            input_ports: ClassVar[dict] = {
                "input": InputPort(name="input", data_type=object)
            }
            output_ports: ClassVar[dict] = {
                "output": OutputPort(name="output", data_type=object)
            }
            metadata: ClassVar[NodeMetadata] = NodeMetadata(
                node_type="_test_trainerish",
                label="Trainerish",
                description="stamp regression",
                category="Test",
            )

            class Config(_TrainerLikeConfig):
                pass

            def process(self, inputs: dict) -> dict:
                return {"output": inputs.get("input")}

        node = _Trainerish(
            config={
                "output_path": "workspace/artifacts/speech-commands",
                "project": "r2",
                "output_dir": "/workspace/datasets/output/r2",
                "version_tag": "v1",
            }
        )
        assert node.config.output_path == "workspace/artifacts/speech-commands"
        dumped = node.config.model_dump()
        assert "project" not in dumped
        assert "output_dir" not in dumped
        assert "version_tag" not in dumped
