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
