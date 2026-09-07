# unit_test/core/plugins/test_store.py
"""Tests for PluginStore — save/load round-trip and update_enabled (Req 6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.plugins.store import PluginRecord, PluginStore
from app.core.plugins.errors import PluginNotFoundError


def _make_record(name: str = "test-plugin", enabled: bool = True) -> PluginRecord:
    return PluginRecord(
        name=name,
        version="1.0.0",
        source="/tmp/test-plugin",
        install_path="/tmp/plugins/test-plugin",
        enabled=enabled,
        installed_at="2024-01-01T00:00:00+00:00",
        manifest={
            "name": name,
            "version": "1.0.0",
            "description": "Test plugin.",
            "author": "Tester",
            "platform_version": ">=0.0",
            "entry_points": ["nodes.py"],
        },
    )


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """Req 6 — PluginRecord save/load round-trip preserves all fields."""
    store = PluginStore(base_dir=str(tmp_path))
    record = _make_record()
    store.save(record)

    loaded = store.get(record.name)
    assert loaded.name == record.name
    assert loaded.version == record.version
    assert loaded.source == record.source
    assert loaded.install_path == record.install_path
    assert loaded.enabled == record.enabled
    assert loaded.installed_at == record.installed_at
    assert loaded.manifest == record.manifest


def test_get_nonexistent_raises(tmp_path: Path) -> None:
    """get() raises PluginNotFoundError for unknown plugin name."""
    store = PluginStore(base_dir=str(tmp_path))
    with pytest.raises(PluginNotFoundError):
        store.get("nonexistent")


def test_update_enabled_toggles_to_false(tmp_path: Path) -> None:
    """Req 6 — update_enabled(False) persists enabled=False."""
    store = PluginStore(base_dir=str(tmp_path))
    record = _make_record(enabled=True)
    store.save(record)

    updated = store.update_enabled(record.name, enabled=False)
    assert updated.enabled is False

    # Verify persistence
    reloaded = store.get(record.name)
    assert reloaded.enabled is False


def test_update_enabled_toggles_to_true(tmp_path: Path) -> None:
    """Req 6 — update_enabled(True) persists enabled=True."""
    store = PluginStore(base_dir=str(tmp_path))
    record = _make_record(enabled=False)
    store.save(record)

    updated = store.update_enabled(record.name, enabled=True)
    assert updated.enabled is True

    reloaded = store.get(record.name)
    assert reloaded.enabled is True


def test_update_enabled_nonexistent_raises(tmp_path: Path) -> None:
    """update_enabled raises PluginNotFoundError for unknown plugin."""
    store = PluginStore(base_dir=str(tmp_path))
    with pytest.raises(PluginNotFoundError):
        store.update_enabled("nonexistent", enabled=False)


def test_list_returns_all_records(tmp_path: Path) -> None:
    """list() returns all saved records."""
    store = PluginStore(base_dir=str(tmp_path))
    r1 = _make_record("plugin-a")
    r2 = _make_record("plugin-b")
    store.save(r1)
    store.save(r2)

    records = store.list()
    names = {r.name for r in records}
    assert "plugin-a" in names
    assert "plugin-b" in names


def test_delete_removes_record(tmp_path: Path) -> None:
    """delete() removes the record so get() raises afterwards."""
    store = PluginStore(base_dir=str(tmp_path))
    record = _make_record()
    store.save(record)
    store.delete(record.name)

    with pytest.raises(PluginNotFoundError):
        store.get(record.name)


def test_save_overwrites_existing(tmp_path: Path) -> None:
    """save() overwrites an existing record with the same name."""
    store = PluginStore(base_dir=str(tmp_path))
    r1 = _make_record(enabled=True)
    store.save(r1)

    r2 = PluginRecord(
        name=r1.name,
        version="2.0.0",
        source=r1.source,
        install_path=r1.install_path,
        enabled=False,
        installed_at=r1.installed_at,
        manifest=r1.manifest,
    )
    store.save(r2)

    loaded = store.get(r1.name)
    assert loaded.version == "2.0.0"
    assert loaded.enabled is False


# ---------------------------------------------------------------------------
# PLUGIN-002 — cross-process / cross-instance registry RMW
# ---------------------------------------------------------------------------


def test_separate_store_instances_share_process_lock(tmp_path: Path) -> None:
    """Separate PluginStore instances for the same registry share one RLock."""
    s1 = PluginStore(base_dir=str(tmp_path))
    s2 = PluginStore(base_dir=str(tmp_path))
    assert s1._lock is s2._lock


def _plugin002_save_worker(base_dir: str, name: str, out_path: str) -> None:
    """Multiprocessing target: save one uniquely named plugin record."""
    from app.core.plugins.store import PluginRecord, PluginStore

    store = PluginStore(base_dir=base_dir)
    store.save(
        PluginRecord(
            name=name,
            version="1.0.0",
            source=f"/tmp/{name}",
            install_path=f"/tmp/plugins/{name}",
            enabled=True,
            installed_at="2024-01-01T00:00:00+00:00",
            manifest={
                "name": name,
                "version": "1.0.0",
                "description": "Concurrent save test.",
                "author": "Tester",
                "platform_version": ">=0.0",
                "entry_points": ["nodes.py"],
            },
        )
    )
    Path(out_path).write_text("ok", encoding="utf-8")


def test_concurrent_saves_no_lost_update(tmp_path: Path) -> None:
    """PLUGIN-002: N processes each save a distinct plugin; none lost."""
    import multiprocessing as mp

    n = 12
    outs = [tmp_path / f"out{i}.txt" for i in range(n)]
    procs = [
        mp.Process(
            target=_plugin002_save_worker,
            args=(str(tmp_path), f"plugin-{i}", str(outs[i])),
        )
        for i in range(n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0, f"worker exited {p.exitcode}"

    for o in outs:
        assert o.read_text(encoding="utf-8") == "ok"

    store = PluginStore(base_dir=str(tmp_path))
    names = {r.name for r in store.list()}
    assert names == {f"plugin-{i}" for i in range(n)}


def _plugin002_toggle_worker(base_dir: str, name: str, rounds: int, out_path: str) -> None:
    """Flip enabled flag repeatedly under flock RMW."""
    from app.core.plugins.store import PluginStore

    store = PluginStore(base_dir=base_dir)
    for i in range(rounds):
        store.update_enabled(name, enabled=(i % 2 == 0))
    Path(out_path).write_text("ok", encoding="utf-8")


def test_concurrent_update_enabled_no_corruption(tmp_path: Path) -> None:
    """PLUGIN-002: concurrent update_enabled on one record stays valid JSON."""
    import multiprocessing as mp

    store = PluginStore(base_dir=str(tmp_path))
    store.save(_make_record("shared-plugin", enabled=True))

    n = 6
    outs = [tmp_path / f"tog{i}.txt" for i in range(n)]
    procs = [
        mp.Process(
            target=_plugin002_toggle_worker,
            args=(str(tmp_path), "shared-plugin", 20, str(outs[i])),
        )
        for i in range(n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0, f"worker exited {p.exitcode}"

    final = store.get("shared-plugin")
    assert final.name == "shared-plugin"
    assert isinstance(final.enabled, bool)
