"""Data-store fixes — pipeline versions / environments / If-Match / ship.

Regressions: lexicographic version sort (v9 "latest" over v10), unlocked
vN allocation (concurrent publishes overwrote each other), corrupt
environments.json read as {} (next write erased prod), and If-Match
check-then-write races in project_pipelines / ship_packages.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest


_REAL_THREAD_START = threading.Thread.start  # captured at collection time


@pytest.fixture(autouse=True)
def patch_threads():
    """Real threads: these tests exercise concurrency.

    Overrides conftest's no-op patch and also guards against another test
    having leaked a patched ``Thread.start`` (restored afterwards unchanged).
    """
    saved = threading.Thread.start
    threading.Thread.start = _REAL_THREAD_START
    try:
        yield
    finally:
        threading.Thread.start = saved


GRAPH = {
    "schema_version": "1.0",
    "metadata": {"name": "p", "seed": 1},
    "nodes": [{"id": "n0", "node_type": "set_map", "config": {"set": {"k": "v"}}}],
    "edges": [],
}


def _graph(tag: str) -> dict:
    g = json.loads(json.dumps(GRAPH))
    g["nodes"][0]["config"]["set"]["k"] = tag
    return g


def _run_threads(n: int, target) -> list:
    results: list = [None] * n
    barrier = threading.Barrier(n)

    def wrap(i: int) -> None:
        barrier.wait()
        try:
            results[i] = ("ok", target(i))
        except BaseException as exc:  # noqa: BLE001
            results[i] = ("err", exc)

    threads = [threading.Thread(target=wrap, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return results


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    from app.core.pipelines.project_pipelines import put_pipeline

    d = tmp_path / "proj"
    d.mkdir()
    put_pipeline(d, "p", _graph("head"), project_name="proj")
    return d


def test_versions_sort_numerically(proj: Path):
    from app.core.pipelines.pipeline_environments import (
        enrich_pipeline_summary,
        list_versions,
        publish_version,
    )

    for _ in range(11):
        publish_version(proj, "p", project_name="proj")
    ids = [v["version"] for v in list_versions(proj, "p")]
    assert ids[:3] == ["v11", "v10", "v9"]
    assert enrich_pipeline_summary(proj, {"name": "p"})["latest_version"] == "v11"


def test_concurrent_publish_allocates_distinct_versions(proj: Path):
    from app.core.pipelines.pipeline_environments import list_versions, publish_version

    res = _run_threads(8, lambda i: publish_version(proj, "p", project_name="proj", message=f"m{i}"))
    assert all(r[0] == "ok" for r in res), res
    vids = sorted((r[1]["version"] for r in res), key=lambda v: int(v[1:]))
    assert vids == [f"v{i}" for i in range(1, 9)]
    msgs = {v["message"] for v in list_versions(proj, "p")}
    assert msgs == {f"m{i}" for i in range(8)}


def test_corrupt_environments_refuses_write_and_quarantines(proj: Path):
    from app.core.pipelines.pipeline_environments import (
        EnvironmentsCorrupt,
        environments_path,
        get_environments,
        list_versions,
        publish_version,
    )

    publish_version(proj, "p", project_name="proj", set_env="staging")
    envp = environments_path(proj, "p")
    envp.write_text('{"prod": "v1", "staging": ')  # truncated
    before = envp.read_bytes()

    with pytest.raises(EnvironmentsCorrupt):
        publish_version(proj, "p", project_name="proj", set_env="staging")
    with pytest.raises(EnvironmentsCorrupt):
        get_environments(proj, "p")
    assert envp.read_bytes() == before  # never overwritten
    assert list(envp.parent.glob("environments.json.corrupt-*"))
    # The aborted publish did not leave an orphan v2.
    assert [v["version"] for v in list_versions(proj, "p")] == ["v1"]


def test_concurrent_promote_requests_all_serialize(proj: Path):
    from app.core.pipelines.pipeline_environments import (
        get_environments,
        promote_environment,
        publish_version,
    )

    for _ in range(3):
        publish_version(proj, "p", project_name="proj")
    res = _run_threads(
        6, lambda i: promote_environment(proj, "p", to_env="staging", version=f"v{i % 3 + 1}")
    )
    assert all(r[0] == "ok" for r in res), res
    assert get_environments(proj, "p")["staging"] in {"v1", "v2", "v3"}


def test_pipeline_if_match_race_one_winner(proj: Path):
    from app.core.errors import VersionConflict
    from app.core.pipelines.project_pipelines import get_pipeline, put_pipeline

    rv = get_pipeline(proj, "p")["resource_version"]
    res = _run_threads(
        6,
        lambda i: put_pipeline(
            proj, "p", _graph(f"w{i}"), project_name="proj",
            expected_resource_version=rv, via_if_match=True,
        ),
    )
    oks = [r for r in res if r[0] == "ok"]
    conflicts = [r for r in res if r[0] == "err" and isinstance(r[1], VersionConflict)]
    assert len(oks) == 1 and len(conflicts) == 5


def test_pipeline_resource_version_is_content_token(proj: Path):
    from app.core.pipelines.project_pipelines import get_pipeline, put_pipeline

    a = put_pipeline(proj, "p", _graph("a"), project_name="proj")["resource_version"]
    b = put_pipeline(proj, "p", _graph("b"), project_name="proj")["resource_version"]
    assert a != b  # two writes in one mtime tick used to look identical
    got = get_pipeline(proj, "p")
    assert got["resource_version"] == b
    # Token from GET is accepted by PUT.
    put_pipeline(proj, "p", _graph("c"), project_name="proj", expected_resource_version=b)


def test_pipeline_legacy_mtime_token_still_accepted(proj: Path):
    from app.core.pipelines.project_pipelines import _pipeline_path, put_pipeline

    legacy = str(_pipeline_path(proj, "p").stat().st_mtime_ns)
    put_pipeline(proj, "p", _graph("z"), project_name="proj", expected_resource_version=legacy)


def test_ship_promote_if_match_race_one_winner(tmp_path: Path):
    from app.core.errors import VersionConflict
    from app.core.mlops.ship_packages import get_package, package_dir, promote_package

    pkg = package_dir(tmp_path, "pkg-race")
    pkg.mkdir(parents=True)
    (pkg / "manifest.json").write_text(json.dumps({
        "package_id": "pkg-race", "status": "signed", "env": "draft",
        "resource_version": 1, "unsigned_allowed": True,
    }))
    res = _run_threads(
        6,
        lambda i: promote_package(
            tmp_path, "pkg-race", to_env="staging",
            expected_resource_version="1", via_if_match=True,
        ),
    )
    oks = [r for r in res if r[0] == "ok"]
    conflicts = [r for r in res if r[0] == "err" and isinstance(r[1], VersionConflict)]
    assert len(oks) == 1 and len(conflicts) == 5
    assert get_package(tmp_path, "pkg-race")["resource_version"] == 2


def test_ship_transition_if_match_race_one_winner(tmp_path: Path):
    from app.core.errors import VersionConflict
    from app.core.mlops.ship_packages import package_dir, transition_package

    pkg = package_dir(tmp_path, "pkg-t")
    pkg.mkdir(parents=True)
    (pkg / "manifest.json").write_text(json.dumps({
        "package_id": "pkg-t", "status": "built", "resource_version": 3,
        "unsigned_allowed": True,
    }))
    res = _run_threads(
        5,
        lambda i: transition_package(
            tmp_path, "pkg-t", "sign", expected_resource_version="3", via_if_match=True,
        ),
    )
    assert sum(r[0] == "ok" for r in res) == 1
    assert sum(r[0] == "err" and isinstance(r[1], VersionConflict) for r in res) == 4
