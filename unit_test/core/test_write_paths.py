"""Engine-level write-destination mkdir (not ingest/read paths)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.write_paths import WRITE_CONFIG_KEYS, ensure_node_write_dirs, ensure_write_destination


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("app.core.config.project_dir", lambda: tmp_path)
    return tmp_path


class TestEnsureWriteDestination:
    def test_creates_directory(self, project: Path) -> None:
        dest = project / "artifacts" / "demo" / "out"
        assert not dest.exists()
        got = ensure_write_destination(str(dest))
        assert got == dest.resolve()
        assert dest.is_dir()

    def test_file_suffix_mkdirs_parent(self, project: Path) -> None:
        file_path = project / "artifacts" / "demo" / "model.keras"
        got = ensure_write_destination(str(file_path))
        assert got == file_path.parent.resolve()
        assert file_path.parent.is_dir()
        assert not file_path.exists()

    def test_refuses_outside_jail(self, project: Path, tmp_path: Path) -> None:
        outside = Path("/etc/graphyn-should-not-exist")
        assert ensure_write_destination(str(outside)) is None
        assert not outside.exists()

    def test_workspace_relative(self, project: Path) -> None:
        got = ensure_write_destination("workspace/artifacts/speech-commands/model")
        assert got is not None
        assert got.is_dir()
        assert (project / "artifacts" / "speech-commands" / "model").is_dir() or (
            project / "workspace" / "artifacts" / "speech-commands" / "model"
        ).is_dir()


class TestEnsureNodeWriteDirs:
    def test_mkdirs_write_keys_only(self, project: Path) -> None:
        ingest = project / "missing-ingest"
        out = project / "artifacts" / "run" / "export"
        node = SimpleNamespace(
            config={
                "path": str(ingest),
                "model_path": str(project / "missing-model.keras"),
                "output_dir": str(out),
            }
        )
        created = ensure_node_write_dirs(node)
        assert out.is_dir()
        assert any(str(out.resolve()) == c for c in created)
        assert not ingest.exists()
        assert not (project / "missing-model.keras").exists()

    def test_pydantic_style_config(self, project: Path) -> None:
        out = project / "artifacts" / "ckpt"
        cfg = SimpleNamespace(
            model_dump=lambda: {"checkpoint_dir": str(out), "path": str(project / "src")}
        )
        node = SimpleNamespace(config=cfg)
        ensure_node_write_dirs(node)
        assert out.is_dir()
        assert not (project / "src").exists()

    def test_write_keys_do_not_include_reads(self) -> None:
        assert "path" not in WRITE_CONFIG_KEYS
        assert "model_path" not in WRITE_CONFIG_KEYS
        assert "input_path" not in WRITE_CONFIG_KEYS
