# unit_test/core/test_pipeline_environments.py
"""Tests for draft/staging/prod pipeline versioning."""
from __future__ import annotations

from pathlib import Path

from app.core.pipeline_environments import (
    get_environment_graph,
    get_environments,
    list_versions,
    promote_environment,
    publish_version,
)
from app.core.project_pipelines import put_pipeline


def _graph(name: str = "hello"):
    return {
        "schema_version": "1.0",
        "metadata": {"name": name, "seed": 1},
        "nodes": [{"id": "n0", "node_type": "set_map", "config": {"set": {"k": "v"}}}],
        "edges": [],
    }


def test_publish_and_promote_prod_requires_approve(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    put_pipeline(project, "main", _graph(), project_name="proj")

    pub = publish_version(
        project, "main", project_name="proj", message="first", set_env="staging", actor="t"
    )
    assert pub["version"] == "v1"
    envs = get_environments(project, "main")
    assert envs["staging"] == "v1"
    assert envs["prod"] is None

    pending = promote_environment(
        project, "main", to_env="prod", from_env="staging", approve=False, actor="t"
    )
    assert pending["status"] == "pending_approval"
    assert get_environments(project, "main")["pending_prod"]["version"] == "v1"

    done = promote_environment(
        project, "main", to_env="prod", version="v1", approve=True, actor="t"
    )
    assert done["status"] == "promoted"
    assert get_environments(project, "main")["prod"] == "v1"
    assert list_versions(project, "main")[0]["version"] == "v1"
    g = get_environment_graph(project, "main", "prod")
    assert g["nodes"][0]["id"] == "n0"
