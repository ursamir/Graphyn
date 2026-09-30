"""Data-store fixes — ProjectManager atomic writes + per-project locking.

Regression: concurrent POST /projects/{name}/annotations truncated
annotations.jsonl ("w" + unlocked read-merge-write) and 2000 annotations
collapsed to 8; GETs mid-write hit JSONDecodeError.
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


@pytest.fixture
def pm(tmp_workspace: Path):
    from app.domain.project_manager import ProjectManager

    mgr = ProjectManager()
    mgr.create("conc")
    return mgr


def _run_threads(n: int, target) -> list[BaseException]:
    errors: list[BaseException] = []
    barrier = threading.Barrier(n)

    def wrap(i: int) -> None:
        try:
            barrier.wait()
            target(i)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=wrap, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return errors


def test_concurrent_add_annotations_loses_nothing(pm):
    per_thread, n = 250, 8

    def add(i: int) -> None:
        batch = [
            {"sample_path": f"t{i}/s{j}.wav", "label": "yes"} for j in range(per_thread)
        ]
        # Several small calls per thread maximizes interleaving.
        for k in range(0, per_thread, 25):
            pm.add_annotations("conc", batch[k : k + 25])

    assert _run_threads(n, add) == []
    assert len(pm.get_annotations("conc")) == per_thread * n


def test_reads_never_see_partial_files_during_writes(pm):
    stop = threading.Event()
    read_errors: list[BaseException] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                pm.get("conc")
                pm.get_taxonomy("conc")
                pm.get_contract("conc")
                pm.get_curation_decisions("conc")
            except BaseException as exc:  # noqa: BLE001
                read_errors.append(exc)
                return

    readers = [threading.Thread(target=reader) for _ in range(3)]
    for t in readers:
        t.start()

    def write(i: int) -> None:
        for j in range(40):
            pm.set_taxonomy("conc", [{"name": f"n{i}-{j}", "children": []}])
            pm.set_contract("conc", {"min_duration_ms": 1, "max_duration_ms": 2 + j})
            pm.set_status("conc", "in-progress")
            pm.add_curation_decision("conc", f"p{i}-{j}", "keep")

    try:
        assert _run_threads(4, write) == []
    finally:
        stop.set()
        for t in readers:
            t.join(30)
    assert read_errors == []
    # Every curation decision from every writer survived.
    assert len(pm.get_curation_decisions("conc")) == 4 * 40


def test_concurrent_add_links_merge(pm):
    def add(i: int) -> None:
        pm.add_links("conc", inputs=[f"input_{i}"])

    assert _run_threads(8, add) == []
    assert sorted(pm.get_links("conc")["inputs"]) == sorted(f"input_{i}" for i in range(8))
    meta = json.loads((pm.BASE / "conc" / "project.json").read_text())
    assert len(meta["links"]["inputs"]) == 8


def test_no_tmp_or_lock_leaks_into_snapshots(pm):
    pm.add_annotations("conc", [{"sample_path": "a.wav", "label": "x"}])
    pm.create_snapshot("conc", "s1")
    snap = pm.BASE / "conc" / "snapshots" / "s1"
    names = {p.name for p in snap.iterdir()}
    assert "annotations.jsonl" in names
    assert not any(n.endswith(".tmp") or n.endswith(".lock") for n in names)
    # No tmp files left behind in the project dir either.
    assert not [p for p in (pm.BASE / "conc").iterdir() if p.name.endswith(".tmp")]


def test_concurrent_create_exactly_one_wins(tmp_workspace: Path):
    from app.domain.project_manager import ProjectManager

    mgr = ProjectManager()
    results: list[str] = []

    def create(_i: int) -> None:
        try:
            mgr.create("race")
            results.append("ok")
        except ValueError:
            results.append("exists")

    assert _run_threads(6, create) == []
    assert results.count("ok") == 1


def test_locked_write_on_deleted_project_is_404_not_resurrect(pm):
    pm.delete("conc", "conc")
    with pytest.raises(FileNotFoundError):
        pm.add_annotations("conc", [{"sample_path": "a.wav", "label": "x"}])
    assert not (pm.BASE / "conc").exists()
