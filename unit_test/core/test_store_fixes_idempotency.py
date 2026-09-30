"""Data-store fixes — Idempotency-Key in-flight reservation.

Regression: begin_idempotent only looked for a *completed* entry, so two
concurrent requests with one key both executed (double run-async / double
ship package).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request


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


@pytest.fixture(autouse=True)
def _fresh_store(tmp_workspace: Path):
    import app.api.idempotency as idem

    idem._MEMORY.clear()
    yield
    idem._MEMORY.clear()


def _req(key: str = "k-1", path: str = "/api/v1/x") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"idempotency-key", key.encode())],
            "query_string": b"",
        }
    )


def test_concurrent_same_key_only_one_executes():
    from app.api.idempotency import begin_idempotent

    n = 8
    barrier = threading.Barrier(n)
    owners: list[int] = []
    in_progress: list[int] = []
    other: list[BaseException] = []

    def go(i: int) -> None:
        barrier.wait()
        try:
            if begin_idempotent(_req(), body={"a": 1}) is None:
                owners.append(i)
        except HTTPException as exc:
            if exc.status_code == 409 and exc.detail["code"] == "idempotency_in_progress":
                in_progress.append(i)
            else:
                other.append(exc)
        except BaseException as exc:  # noqa: BLE001
            other.append(exc)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert other == []
    assert len(owners) == 1
    assert len(in_progress) == n - 1


def test_complete_then_replay_and_body_conflict():
    from app.api.idempotency import begin_idempotent, complete_idempotent

    r1 = _req()
    assert begin_idempotent(r1, body={"a": 1}) is None
    complete_idempotent(r1, status_code=201, body={"id": "x"})

    replay = begin_idempotent(_req(), body={"a": 1})
    assert replay is not None and replay.status_code == 201
    assert replay.headers["Idempotent-Replay"] == "true"
    assert json.loads(replay.body) == {"id": "x"}

    with pytest.raises(HTTPException) as ei:
        begin_idempotent(_req(), body={"a": 2})
    assert ei.value.detail["error"] == "idempotency_conflict"


def test_in_progress_different_body_is_conflict():
    from app.api.idempotency import begin_idempotent

    assert begin_idempotent(_req(), body={"a": 1}) is None
    with pytest.raises(HTTPException) as ei:
        begin_idempotent(_req(), body={"a": 2})
    assert ei.value.detail["error"] == "idempotency_conflict"


def test_abort_releases_so_retry_can_run():
    from app.api.idempotency import abort_idempotent, begin_idempotent, idempotency_guard

    r1 = _req()
    assert begin_idempotent(r1, body={"a": 1}) is None
    with pytest.raises(RuntimeError):
        with idempotency_guard(r1):
            raise RuntimeError("handler failed")
    # Placeholder removed → a retry with the same key executes.
    r2 = _req()
    assert begin_idempotent(r2, body={"a": 1}) is None
    abort_idempotent(r2)
    abort_idempotent(r2)  # idempotent / no-op


def test_abort_never_deletes_someone_elses_entry():
    import app.api.idempotency as idem
    from app.api.idempotency import abort_idempotent, begin_idempotent, complete_idempotent

    r1 = _req()
    assert begin_idempotent(r1, body={"a": 1}) is None
    token = r1.state.idempotency_token
    comp = r1.state.idempotency_comp
    complete_idempotent(r1, status_code=200, body={"ok": True})
    # A late abort with the old token must not remove the completed entry.
    r1.state.idempotency_comp = comp
    r1.state.idempotency_token = token
    abort_idempotent(r1)
    assert idem._read_disk(comp)["state"] == "completed"


def test_stale_placeholder_expires():
    import app.api.idempotency as idem
    from app.api.idempotency import begin_idempotent

    r1 = _req()
    assert begin_idempotent(r1, body={"a": 1}) is None
    comp = r1.state.idempotency_comp
    data = idem._read_disk(comp)
    data["started_at"] = time.time() - idem.IN_PROGRESS_TTL_S - 5
    idem._entry_path(comp).write_text(json.dumps(data))
    # Crashed owner: a new request may take over.
    assert begin_idempotent(_req(), body={"a": 1}) is None


def test_failed_api_request_does_not_block_retry(api_client, tmp_workspace):
    headers = {"Idempotency-Key": "proj-bad-1"}
    r1 = api_client.post("/api/v1/projects", json={"name": "bad name!"}, headers=headers)
    assert r1.status_code in (400, 422)
    r2 = api_client.post("/api/v1/projects", json={"name": "bad name!"}, headers=headers)
    # Before the guard the placeholder would have stuck as in_progress (409).
    assert r2.status_code == r1.status_code

    ok_headers = {"Idempotency-Key": "proj-ok-1"}
    a = api_client.post("/api/v1/projects", json={"name": "idem_ok"}, headers=ok_headers)
    b = api_client.post("/api/v1/projects", json={"name": "idem_ok"}, headers=ok_headers)
    assert a.status_code == 200 and b.status_code == 200
    assert b.headers.get("Idempotent-Replay") == "true"
