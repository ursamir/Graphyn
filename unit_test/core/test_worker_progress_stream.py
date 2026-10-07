"""Mode B: emit_node_progress on the worker reaches the control run journal."""
from __future__ import annotations

import time

import pytest

from app.core.distributed.models import NodeJob, WorkerInfo
from app.core.distributed.queue import _reset_job_queue, get_job_queue
from app.core.distributed.registry import _reset_worker_registry, get_worker_registry
from app.core.distributed.worker_progress import JobProgressPublisher
from app.core.nodes.progress import emit_node_progress, progress_context


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    """Publisher flushes on a daemon thread — need real Thread.start."""
    yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    _reset_worker_registry()
    _reset_job_queue(use_memory=True, lease_ttl_s=60.0)
    yield
    _reset_worker_registry()
    _reset_job_queue(use_memory=True)


def test_job_progress_publisher_batches_and_flushes():
    posted: list[list[dict]] = []

    def post(jid, evs):
        posted.append((jid, list(evs)))

    pub = JobProgressPublisher("j1", post, flush_interval_s=0.15, batch_size=3)
    try:
        for i in range(3):
            pub.sink({"type": "node_progress", "epoch": i, "node_id": "t0"})
        time.sleep(0.05)
        assert posted and posted[0][0] == "j1" and len(posted[0][1]) == 3
        pub.sink({"type": "node_progress", "epoch": 3, "node_id": "t0"})
        pub.sink({"type": "outputs", "data": {}})  # dropped
    finally:
        pub.close()
    epochs = [e["epoch"] for _, batch in posted for e in batch]
    assert 3 in epochs and all("type" in e for _, batch in posted for e in batch)


def test_emit_node_progress_via_publisher_lands_in_queue(env):
    q = get_job_queue()
    get_worker_registry().register(
        WorkerInfo(worker_id="w1", plugins=["trainer"], status="idle")
    )
    q.enqueue(
        NodeJob(
            job_id="jprog",
            run_id="r1",
            node_id="trainer_0",
            node_type="trainer",
            pool=None,
        )
    )
    claimed = q.claim(get_worker_registry().get("w1"))
    assert claimed and claimed.job_id == "jprog"

    pub = JobProgressPublisher(
        "jprog",
        lambda jid, evs: q.append_events(jid, evs),
        flush_interval_s=0.1,
        batch_size=1,
    )
    try:
        with progress_context("trainer_0", "trainer", pub.sink):
            emit_node_progress(
                {"phase": "train", "epoch": 2, "epochs": 50, "loss": 0.4, "accuracy": 0.8, "pct": 4.0}
            )
            emit_node_progress(
                {
                    "phase": "train",
                    "epoch": 50,
                    "epochs": 50,
                    "loss": 0.1,
                    "accuracy": 0.95,
                    "pct": 100.0,
                    "final": True,
                }
            )
    finally:
        pub.close()

    events = q.list_events("jprog")
    progress = [e for e in events if e.get("type") == "node_progress"]
    assert len(progress) >= 2
    assert any(e.get("epoch") == 2 for e in progress)
    assert any("Trainer" in str(e.get("message") or "") for e in progress)


def test_forward_job_events_writes_journal_and_meta(env):
    from app.core.distributed import backend as be

    q = get_job_queue()
    get_worker_registry().register(
        WorkerInfo(worker_id="w1", plugins=["set_map"], status="idle")
    )
    q.enqueue(NodeJob(job_id="jf", run_id="r1", node_id="n1", node_type="set_map"))
    q.claim(get_worker_registry().get("w1"))
    q.append_events(
        "jf",
        [
            {
                "type": "node_progress",
                "node_id": "n1",
                "node_type": "set_map",
                "epoch": 1,
                "message": "Set map · epoch 1/2",
            }
        ],
    )

    journal: list[dict] = []

    class _Log:
        def node_progress(self, ev):
            journal.append(ev)

        def info(self, msg):
            pass

    class _Run:
        _latest_node_progress = None

        def _write_meta_field(self, k, v):
            setattr(self, k, v)

    run = _Run()
    seen: set[int] = set()
    n = be._forward_job_events(
        q, "jf", logger=_Log(), run=run, node_id="n1", seen=seen
    )
    assert n == 1 and journal and journal[0]["epoch"] == 1
    assert run.node_progress["n1"]["epoch"] == 1
    # Idempotent: already-seen seq is not re-forwarded.
    assert be._forward_job_events(q, "jf", logger=_Log(), run=run, node_id="n1", seen=seen) == 0
