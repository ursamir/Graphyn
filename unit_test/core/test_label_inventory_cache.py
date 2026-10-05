"""Cached label inventory for large input trees (Phase E)."""
from __future__ import annotations

from pathlib import Path

from app.core.mlops.dataset_inputs import (
    LABEL_INVENTORY_DIR,
    invalidate_label_inventory,
    label_counts,
)


def test_label_counts_writes_and_reuses_inventory(tmp_path: Path):
    label = tmp_path / "speech"
    label.mkdir()
    (label / "a.wav").write_bytes(b"RIFF")
    (label / "b.txt").write_text("x")

    first = label_counts(label)
    assert first == {"file_count": 2, "audio_count": 1}
    inv = tmp_path / LABEL_INVENTORY_DIR / "speech.json"
    assert inv.is_file()

    # Second call must hit cache (signature unchanged) even if we could not
    # prove no walk — inventory file stays and counts stay stable.
    second = label_counts(label)
    assert second == first

    (label / "c.wav").write_bytes(b"RIFF")
    third = label_counts(label)
    assert third == {"file_count": 3, "audio_count": 2}


def test_invalidate_label_inventory(tmp_path: Path):
    label = tmp_path / "lab"
    label.mkdir()
    (label / "a.wav").write_bytes(b"x")
    label_counts(label)
    inv = tmp_path / LABEL_INVENTORY_DIR / "lab.json"
    assert inv.is_file()
    invalidate_label_inventory(label)
    assert not inv.exists()
