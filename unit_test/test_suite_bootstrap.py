# unit_test/test_suite_bootstrap.py
"""Bootstrap smoke test — verifies the unit_test suite infrastructure is importable.

This file ensures `venv/bin/pytest unit_test/ --collect-only` exits 0 even before
individual test modules are written (Req 1 criterion 2).
"""
from __future__ import annotations


def test_conftest_imports() -> None:
    """Verify that all conftest fixtures are importable without error."""
    from app.core.nodes.registry import NodeRegistry
    from app.models.audio_sample import AudioSample
    import numpy as np

    # NodeRegistry instantiates cleanly
    reg = NodeRegistry()
    assert len(reg) == 0

    # AudioSample constructs with numpy data
    data = np.zeros(16000, dtype=np.float32)
    sample = AudioSample(path="/fake/audio.wav", sample_rate=16000, data=data, label="test")
    assert sample.sample_rate == 16000
    assert sample.label == "test"
