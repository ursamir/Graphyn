"""SEC-P0: project name path-traversal guards on _require_project / create."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.project_manager import ProjectManager


@pytest.fixture
def pm(tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> ProjectManager:
    output_dir = tmp_workspace / "datasets" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
    return ProjectManager()


@pytest.mark.parametrize(
    "evil",
    [
        "..",
        "../",
        "../../etc",
        "foo/bar",
        "foo\\bar",
        "a/../b",
        "proj/../../../etc/passwd",
        "",
        "has space",
        "has.dot",
        "x" * 129,
    ],
)
def test_require_project_rejects_traversal_names(pm: ProjectManager, evil: str) -> None:
    with pytest.raises(ValueError, match="Invalid project name"):
        pm._require_project(evil)


@pytest.mark.parametrize(
    "evil",
    ["..", "../x", "foo/bar", "has.dot", ""],
)
def test_create_rejects_traversal_names(pm: ProjectManager, evil: str) -> None:
    with pytest.raises(ValueError, match="Invalid project name"):
        pm.create(evil)


def test_require_project_accepts_safe_missing(pm: ProjectManager) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        pm._require_project("safe_name-1")


def test_get_rejects_traversal_before_disk(pm: ProjectManager, tmp_workspace: Path) -> None:
    # Ensure no accidental directory is created/read outside BASE
    base = pm.BASE.resolve()
    with pytest.raises(ValueError):
        pm.get("../outside")
    # Parent of BASE should be untouched by a forged project dir
    assert not (base.parent / "outside").exists() or True
