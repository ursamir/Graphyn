# unit_test/core/test_model_registry.py
from __future__ import annotations

from pathlib import Path

from app.core.model_registry import (
    approve_prod,
    get_model,
    list_models,
    register_model,
    request_prod,
)


def test_register_request_approve(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    # seed artifact tree for publish_alias
    run_id = "run-m1"
    slug = "speech-demo"
    art = tmp_path / "artifacts" / slug / "runs" / run_id
    art.mkdir(parents=True)
    (art / "model.bin").write_bytes(b"x")

    rec = register_model(
        "wakeword",
        run_id=run_id,
        slug=slug,
        stage="staging",
        actor="t",
        base_dir=tmp_path,
    )
    assert rec["stages"]["staging"]["run_id"] == run_id
    assert list_models(base_dir=tmp_path)[0]["name"] == "wakeword"

    pending = request_prod("wakeword", actor="t", base_dir=tmp_path)
    assert pending["status"] == "pending_approval"
    assert get_model("wakeword", base_dir=tmp_path)["pending_prod"]["run_id"] == run_id

    done = approve_prod("wakeword", actor="t", base_dir=tmp_path)
    assert "prod" in done["stages"]
    assert done.get("pending_prod") in (None, {})
