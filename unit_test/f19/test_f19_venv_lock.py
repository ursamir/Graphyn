# unit_test/f19/test_f19_venv_lock.py
"""F19 / F-03 (found live): Mode B control + worker share the plugin venvs dir.

After a rebuild both containers re-created the drifted ``edge-optimizer`` venv
at once and the worker's half failed (``ensurepip`` exit 1), so the worker came
up without ``edge_optimizer``. Venv create/install/remove is now serialised
with a cross-process ``flock``.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from app.core.plugins.venv_manager import PluginVenvManager


def test_lock_is_exclusive_across_processes(tmp_path: Path):
    mgr = PluginVenvManager(base_dir=tmp_path)
    probe = (
        "import fcntl,sys\n"
        f"fh=open({str(tmp_path / '.locks' / 'p1.lock')!r},'a+')\n"
        "try:\n fcntl.flock(fh.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB); print('free')\n"
        "except BlockingIOError: print('held')\n"
    )
    with mgr._venv_lock("p1"):
        held = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True).stdout.strip()
    free = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True).stdout.strip()
    assert held == "held"
    assert free == "free"


def test_remove_waits_for_an_in_flight_build(tmp_path: Path, real_threads):
    mgr = PluginVenvManager(base_dir=tmp_path)
    (tmp_path / "p2" / "bin").mkdir(parents=True)
    done = threading.Event()

    def _remove():
        mgr.remove("p2")
        done.set()

    with mgr._venv_lock("p2"):  # another container is building this venv
        t = threading.Thread(target=_remove)
        t.start()
        time.sleep(0.3)
        assert not done.is_set()
        assert (tmp_path / "p2").exists()
    t.join(5)
    assert done.is_set() and not (tmp_path / "p2").exists()


def test_ensure_takes_the_lock_and_rechecks(tmp_path: Path, monkeypatch, real_threads):
    mgr = PluginVenvManager(base_dir=tmp_path)
    calls: list[str] = []

    def fake_locked(name, reqs, **kw):
        calls.append(name)
        return tmp_path / name / "bin" / "python"

    monkeypatch.setattr(mgr, "_ensure_locked", fake_locked)
    out: list[Path] = []
    with mgr._venv_lock("p3"):
        t = threading.Thread(target=lambda: out.append(mgr.ensure("p3", [])))
        t.start()
        time.sleep(0.3)
        assert calls == []  # blocked behind the holder
    t.join(5)
    assert calls == ["p3"] and out


def test_gc_skips_bookkeeping_dirs(tmp_path: Path):
    mgr = PluginVenvManager(base_dir=tmp_path)
    with mgr._venv_lock("keep"):
        pass
    (tmp_path / "orphan").mkdir()
    removed = mgr.gc_unused({"keep"})
    assert removed == ["orphan"]
    assert (tmp_path / ".locks").is_dir()


def test_failed_create_leaves_no_half_built_venv(tmp_path, monkeypatch):
    import venv as _venv
    import pytest as _pytest
    from app.core.plugins.errors import PluginInstallError

    mgr = PluginVenvManager(base_dir=tmp_path)

    def boom(self, root):
        (Path(root) / "bin").mkdir(parents=True)
        (Path(root) / "bin" / "python").write_text("")
        raise RuntimeError("ensurepip returned non-zero exit status 1")

    monkeypatch.setattr(_venv.EnvBuilder, "create", boom)
    with _pytest.raises(PluginInstallError):
        mgr.ensure("p5", [])
    assert not (tmp_path / "p5").exists()


def test_incomplete_venv_is_rebuilt(tmp_path, monkeypatch):
    import venv as _venv

    mgr = PluginVenvManager(base_dir=tmp_path)
    (tmp_path / "p6" / "bin").mkdir(parents=True)
    (tmp_path / "p6" / "bin" / "python").write_text("")  # python but no pip
    created: list[str] = []

    def fake_create(self, root):
        created.append(str(root))
        raise RuntimeError("stop after the rebuild decision")

    monkeypatch.setattr(_venv.EnvBuilder, "create", fake_create)
    try:
        mgr.ensure("p6", [])
    except Exception:
        pass
    assert created == [str(tmp_path / "p6")]


def test_remove_keeps_a_venv_another_container_just_rebuilt(tmp_path, monkeypatch):
    import json as _json
    import time as _time
    from app.core.plugins import venv_manager as vm

    mgr = PluginVenvManager(base_dir=tmp_path)
    root = tmp_path / "p7"
    root.mkdir()
    monkeypatch.setattr(vm, "_PROCESS_START", _time.time() - 60)
    (root / vm._BUILD_STAMP).write_text(_json.dumps({"host": "graphyn-api-other", "built_at": _time.time()}))
    mgr.remove("p7")
    assert root.exists()  # rebuilt elsewhere after our boot → kept
    (root / vm._BUILD_STAMP).write_text(_json.dumps({"host": "graphyn-api-other", "built_at": _time.time() - 3600}))
    mgr.remove("p7")
    assert not root.exists()  # stale pre-boot build → removed
