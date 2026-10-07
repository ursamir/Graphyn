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
    assert first == {"file_count": 2, "audio_count": 1, "truncated": False}
    inv = tmp_path / LABEL_INVENTORY_DIR / "speech.json"
    assert inv.is_file()

    second = label_counts(label)
    assert second == first

    (label / "c.wav").write_bytes(b"RIFF")
    third = label_counts(label)
    assert third == {"file_count": 3, "audio_count": 2, "truncated": False}


def test_label_counts_cache_hit_skips_walk(tmp_path: Path, monkeypatch):
    import app.core.mlops.dataset_inputs as di

    label = tmp_path / "speech"
    (label / "yes").mkdir(parents=True)
    (label / "yes" / "a.wav").write_bytes(b"RIFF")
    label_counts(label)

    def _boom(*a, **k):
        raise AssertionError("cache hit must not recount")

    monkeypatch.setattr(di, "count_files_budgeted", _boom)
    assert label_counts(label)["file_count"] == 1


def test_label_counts_sees_new_file_in_class_folder(tmp_path: Path):
    label = tmp_path / "speech"
    (label / "yes").mkdir(parents=True)
    (label / "yes" / "a.wav").write_bytes(b"RIFF")
    assert label_counts(label)["file_count"] == 1
    import os
    import time

    (label / "yes" / "b.wav").write_bytes(b"RIFF")
    later = time.time() + 5
    os.utime(label / "yes", (later, later))
    assert label_counts(label)["file_count"] == 2


def test_label_counts_ttl_catches_deep_edits(tmp_path: Path, monkeypatch):
    label = tmp_path / "speech"
    deep = label / "yes" / "spk1"
    deep.mkdir(parents=True)
    (deep / "a.wav").write_bytes(b"RIFF")
    assert label_counts(label)["file_count"] == 1
    (deep / "b.wav").write_bytes(b"RIFF")
    monkeypatch.setenv("GRAPHYN_INPUT_INVENTORY_TTL_S", "0")
    import time

    time.sleep(0.01)
    assert label_counts(label)["file_count"] == 2


def test_count_budget_exact_at_cap_is_not_truncated(tmp_path: Path):
    from app.core.mlops.dataset_inputs import count_files_budgeted

    for i in range(10):
        (tmp_path / f"{i}.wav").write_bytes(b"x")
    assert count_files_budgeted(tmp_path, max_files=10) == {
        "file_count": 10,
        "audio_count": 10,
        "truncated": False,
    }
    (tmp_path / "extra.wav").write_bytes(b"x")
    out = count_files_budgeted(tmp_path, max_files=10)
    assert out["truncated"] is True and out["file_count"] == 10


def test_invalidate_label_inventory(tmp_path: Path):
    label = tmp_path / "lab"
    label.mkdir()
    (label / "a.wav").write_bytes(b"x")
    label_counts(label)
    inv = tmp_path / LABEL_INVENTORY_DIR / "lab.json"
    assert inv.is_file()
    invalidate_label_inventory(label)
    assert not inv.exists()
