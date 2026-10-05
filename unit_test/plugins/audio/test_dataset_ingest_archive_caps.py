# unit_test/plugins/audio/test_dataset_ingest_archive_caps.py
"""dataset_ingest 1.2.0 — capped, filtered ZIP / TAR extraction."""
from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "PluginPackage" / "Audio" / "dataset_ingest"


@pytest.fixture(scope="module")
def cls():
    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    disc._process_module(disc._import_file(PLUGIN / "nodes.py", package_prefix=None))
    return reg.get_class("dataset_ingest")


def _wav_bytes() -> bytes:
    buf = io.BytesIO()
    sf.write(buf, (0.1 * np.sin(np.arange(1600) / 5.0)).astype(np.float32), 16000, format="WAV")
    return buf.getvalue()


def _zip(path: Path, n: int) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(n):
            zf.writestr(f"yes/a{i}.wav", _wav_bytes())
        zf.writestr("../escape.wav", _wav_bytes())
    return path


def _run(cls, cfg):
    return cls(config=cfg, seed=0).process({})["output"]


def test_version_bumped(cls):
    assert cls.metadata.version == "1.2.0"


def test_zip_loads_and_skips_traversal(cls, tmp_path):
    out = _run(cls, {"source_type": "zip", "path": str(_zip(tmp_path / "d.zip", 3))})
    assert len(out) == 3 and {s.label for s in out} == {"yes"}
    assert not (tmp_path.parent / "escape.wav").exists()


def test_zip_file_cap(cls, tmp_path):
    with pytest.raises(ValueError, match="more than 2 files"):
        _run(cls, {"source_type": "zip", "path": str(_zip(tmp_path / "d.zip", 3)), "max_archive_files": 2})


def test_zip_byte_cap(cls, tmp_path):
    with pytest.raises(ValueError, match="MB"):
        _run(cls, {"source_type": "zip", "path": str(_zip(tmp_path / "d.zip", 400)), "max_archive_mb": 1})


def test_tar_skips_symlinks(cls, tmp_path):
    path = tmp_path / "d.tar"
    data = _wav_bytes()
    with tarfile.open(path, "w") as tf:
        info = tarfile.TarInfo("no/b.wav")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("no/link.wav")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)
    out = _run(cls, {"source_type": "tar", "path": str(path)})
    assert len(out) == 1 and out[0].label == "no"
