"""``…/latest`` dataset paths resolve to the newest non-empty version before a run."""
from app.core.execution.dataset_refs import newest_version_dir, resolve_latest_refs


def _mk(root, name, files=1):
    d = root / name
    d.mkdir(parents=True)
    for i in range(files):
        (d / f"f{i}.wav").write_bytes(b"x")
    return d


def test_newest_version_numeric_order_and_skips_empty(tmp_path):
    _mk(tmp_path, "v2")
    _mk(tmp_path, "v10")
    _mk(tmp_path, "v11", files=0)  # empty → ignored
    (tmp_path / "notes").mkdir()
    assert newest_version_dir(tmp_path) == "v10"


def test_resolve_in_ir_dict(tmp_path):
    base = tmp_path / "ds"
    _mk(base, "v1")
    _mk(base, "v2")
    graph = {
        "ir_version": "1.3",
        "nodes": [{"id": "ingest", "node_type": "dataset_ingest",
                   "config": {"path": f"{base}/latest", "other": "keep/latest/x", "url": "http://h/latest"}}],
        "edges": [],
    }
    new, res = resolve_latest_refs(graph)
    assert new["nodes"][0]["config"]["path"] == f"{base}/v2"
    # no version siblings next to "keep" → untouched; URLs never touched
    assert new["nodes"][0]["config"]["other"] == "keep/latest/x"
    assert new["nodes"][0]["config"]["url"] == "http://h/latest"
    assert res == [{"node_id": "ingest", "key": "path", "ref": f"{base}/latest", "resolved": f"{base}/v2"}]


def test_no_refs_returns_same_object():
    g = {"nodes": [{"id": "a", "config": {"path": "workspace/datasets/input/x"}}], "edges": []}
    new, res = resolve_latest_refs(g)
    assert new is g and res == []
