"""Mode B fixes — HTTP worker loop: unique worker ids, heartbeat v2 payload,
re-register on 404, complete retry with backoff, claimed-generation fencing."""
from __future__ import annotations

import io
import json
import urllib.error
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs

import pytest

from app.cli import main as cli


# ── 2. worker id defaults ───────────────────────────────────────────────────


def test_default_worker_id_is_auto_generated(monkeypatch):
    monkeypatch.delenv("GRAPHYN_WORKER_ID", raising=False)
    a = cli._resolve_worker_id(None, http_mode=True)
    b = cli._resolve_worker_id(None, http_mode=True)
    assert a != b and a != "worker-local"
    import re

    assert re.fullmatch(r"[A-Za-z0-9_.-]+-[0-9a-f]{8}", a)


def test_legacy_worker_local_replaced_in_mode_b(monkeypatch, capsys):
    monkeypatch.delenv("GRAPHYN_WORKER_ID", raising=False)
    wid = cli._resolve_worker_id("worker-local", http_mode=True)
    assert wid != "worker-local"
    assert "WARNING" in capsys.readouterr().err
    # in-process (single machine) keeps an explicit id
    assert cli._resolve_worker_id("worker-local", http_mode=False) == "worker-local"
    monkeypatch.setenv("GRAPHYN_WORKER_ID", "gpu-box-1")
    assert cli._resolve_worker_id(None, http_mode=True) == "gpu-box-1"


def test_heartbeat_payload_carries_active_job_ids():
    body = cli._worker_heartbeat_payload({"gpu": False}, "busy", active_job_ids=["j1"])
    assert body["active_job_ids"] == ["j1"]
    assert body["active_jobs"] == 1
    assert cli._worker_heartbeat_payload({}, "idle")["active_job_ids"] == []


# ── 2. retry helper ─────────────────────────────────────────────────────────


def test_retry_http_retries_transient_then_succeeds():
    calls = {"n": 0}
    sleeps: list[float] = []

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise cli._WorkerHTTPError(503, "HTTP 503 busy")
        return "ok"

    assert cli._retry_http(fn, attempts=5, base_delay_s=0.5, sleep=sleeps.append) == "ok"
    assert sleeps == [0.5, 1.0]


def test_retry_http_does_not_retry_4xx():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise cli._WorkerHTTPError(409, "HTTP 409 fenced")

    with pytest.raises(cli._WorkerHTTPError):
        cli._retry_http(fn, attempts=5, sleep=lambda _s: None)
    assert calls["n"] == 1

    def blob_fn():
        calls["n"] += 1
        raise RuntimeError("HTTP 403 PUT blob: not your claim")

    calls["n"] = 0
    with pytest.raises(RuntimeError):
        cli._retry_http(blob_fn, attempts=5, sleep=lambda _s: None)
    assert calls["n"] == 1


def test_retry_http_gives_up_after_attempts():
    with pytest.raises(OSError):
        cli._retry_http(lambda: (_ for _ in ()).throw(OSError("net down")),
                        attempts=3, sleep=lambda _s: None)


# ── 10 / 2 / 3. HTTP loop against a fake control plane ─────────────────────


class _FakeControl:
    def __init__(self, job: dict | None = None) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.job = job
        self.heartbeat_404 = 1
        self.complete_failures = 2
        self.completed: list[dict] = []

    def urlopen(self, req, timeout=0):
        url = urlparse(req.full_url)
        path = url.path
        body = json.loads(req.data.decode()) if req.data else None
        self.calls.append((req.get_method(), path + (("?" + url.query) if url.query else ""), body))

        def reply(payload, code=200):
            if code != 200:
                raise urllib.error.HTTPError(req.full_url, code, "err", {},
                                             io.BytesIO(json.dumps({"detail": "x"}).encode()))
            return _Ctx(io.BytesIO(json.dumps(payload).encode()))

        if path == "/workers/register":
            return reply({"ok": True})
        if path.endswith("/heartbeat"):
            if self.heartbeat_404 > 0:
                self.heartbeat_404 -= 1
                return reply(None, 404)
            return reply({"ok": True})
        if path == "/jobs/claim":
            job, self.job = self.job, None
            return reply({"job": job})
        if path.endswith("/complete"):
            if self.complete_failures > 0:
                self.complete_failures -= 1
                return reply(None, 503)
            self.completed.append(body)
            return reply({"ok": True})
        if path.startswith("/jobs/"):
            return reply({"job": {"status": "claimed"}, "run_paused": False})
        raise AssertionError(f"unexpected {path}")


class _Ctx:
    def __init__(self, resp):
        self._r = resp

    def __enter__(self):
        return self._r

    def __exit__(self, *a):
        return False


def _args(**kw):
    base = dict(control_url="http://control", worker_id="w-test", labels="", pool=None,
                heartbeat=1, once=True, in_process=False, plugins="only_this_type")
    base.update(kw)
    return SimpleNamespace(**base)


def test_worker_reregisters_on_heartbeat_404(monkeypatch):
    fake = _FakeControl(job=None)
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake.urlopen)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    cli.cmd_worker_start(_args())
    paths = [p for _m, p, _b in fake.calls]
    assert paths[0] == "/workers/register"
    hb_idx = paths.index("/workers/w-test/heartbeat")
    assert paths[hb_idx + 1] == "/workers/register"  # re-register after 404
    hb_bodies = [b for _m, p, b in fake.calls if p.endswith("/heartbeat")]
    assert all("active_job_ids" in b for b in hb_bodies)


def test_worker_retries_complete_and_reports_claimed_generation(monkeypatch):
    job = {"job_id": "job-1", "run_id": "r", "node_id": "n", "node_type": "not_advertised",
           "lease_generation": 4}
    fake = _FakeControl(job=job)
    fake.heartbeat_404 = 0
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake.urlopen)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    cli.cmd_worker_start(_args())
    assert len(fake.completed) == 1  # 2x 503 then success
    assert fake.completed[0]["lease_generation"] == 4
    assert fake.completed[0]["status"] == "failed"
    complete_calls = [p for _m, p, _b in fake.calls if p.endswith("/complete")]
    assert len(complete_calls) == 3
