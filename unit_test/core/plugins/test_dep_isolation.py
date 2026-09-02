# unit_test/core/plugins/test_dep_isolation.py
"""Tests for plugin dependency status, conflict guard, venvs, and runtime field."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.plugins.dependencies import DependencyChecker, PLATFORM_CONSTRAINTS
from app.core.plugins.errors import PluginDependencyError, PluginManifestError
from app.core.plugins.manifest import PluginManifest
from app.core.plugins.runtime_registry import (
    IsolatedPluginSpec,
    PluginRuntimeRegistry,
    get_runtime_registry,
)
from app.core.plugins.venv_manager import PluginVenvManager


def test_manifest_runtime_default_inprocess() -> None:
    m = PluginManifest(
        name="demo-plugin",
        version="1.0.0",
        description="demo",
        author="t",
        platform_version=">=0.0",
        entry_points=["nodes.py"],
    )
    assert m.runtime == "inprocess"


def test_manifest_runtime_isolated() -> None:
    m = PluginManifest(
        name="demo-plugin",
        version="1.0.0",
        description="demo",
        author="t",
        platform_version=">=0.0",
        entry_points=["nodes.py"],
        runtime="isolated",
        optional_dependencies=["pytest>=0.1"],
    )
    assert m.runtime == "isolated"


def test_manifest_runtime_invalid() -> None:
    with pytest.raises(PluginManifestError):
        PluginManifest(
            name="demo-plugin",
            version="1.0.0",
            description="demo",
            author="t",
            platform_version=">=0.0",
            entry_points=["nodes.py"],
            runtime="container",
        )


def test_dependency_status_lists_optional() -> None:
    rows = DependencyChecker().status(
        ["pytest>=0.1"],
        optional_dependencies=["this-package-does-not-exist-graphyn-xyz"],
    )
    assert rows[0].satisfied is True
    assert rows[0].optional is False
    assert rows[1].satisfied is False
    assert rows[1].optional is True


def test_conflict_platform_numpy_pin() -> None:
    conflicts = DependencyChecker().check_conflicts(["numpy>=99"])
    # Either platform requires conflict or installed-version conflict
    assert conflicts


def test_runtime_registry_roundtrip() -> None:
    reg = PluginRuntimeRegistry()
    spec = IsolatedPluginSpec(
        plugin_name="trainer",
        install_path="/tmp/trainer",
        venv_python="/tmp/venv/bin/python",
        node_types=("trainer", "model_builder"),
    )
    reg.register(spec)
    assert reg.get_for_node("trainer") is spec
    reg.unregister_plugin("trainer")
    assert reg.get_for_node("trainer") is None


def test_venv_manager_create_and_gc(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.plugins.venv_manager.DependencyChecker._find_unsatisfied",
        lambda self, parsed, python=None: [],
    )
    monkeypatch.setattr(
        "app.core.plugins.venv_manager.DependencyChecker.install",
        lambda *a, **k: None,
    )
    mgr = PluginVenvManager(base_dir=tmp_path)
    py = mgr.ensure("tiny-plugin", ["pip"])  # pip already present; no-op install
    assert Path(py).exists()
    lock = mgr.lockfile_path("tiny-plugin")
    assert lock.exists()
    removed = mgr.gc_unused(set())
    assert "tiny-plugin" in removed
    assert not mgr.venv_dir("tiny-plugin").exists()


def test_platform_constraints_nonempty() -> None:
    assert any(c.startswith("numpy") for c in PLATFORM_CONSTRAINTS)


# ---------------------------------------------------------------------------
# Isolation fail-closed tests (B1–B3, H1–H6)
# ---------------------------------------------------------------------------

import ast
import io
import pickle
import stat
import zipfile
from typing import ClassVar
from unittest.mock import MagicMock, patch

from app.core.node_executor import NodeExecutor
from app.core.nodes.base import Node
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.registry import NodeRegistry
from app.core.plugins.errors import PluginDependencyError, PluginInstallError
from app.core.plugins.installer import PluginInstaller
from app.core.plugins.isolated_executor import (
    RestrictedUnpickler,
    load_isolated_outputs,
)
from app.core.plugins.loader import PluginLoader, isolated_venv_requirements
from app.core.plugins.manager import PluginManager
from app.core.plugins.store import PluginRecord
from app.core.plugins.venv_manager import PluginVenvManager as _VenvMgr


def _isolated_toml(
    tmp_path: Path,
    *,
    name: str = "iso-plugin",
    node_types: str = '["iso_node"]',
    extra_nodes_py: str = "",
    extra_toml: str = "",
) -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.toml").write_text(
        f'''\
[plugin]
name = "{name}"
version = "1.0.0"
description = "isolated test plugin"
author = "t"
platform_version = ">=0.0"
entry_points = ["nodes.py"]
runtime = "isolated"
node_types = {node_types}
'''
        + extra_toml,
        encoding="utf-8",
    )
    (d / "nodes.py").write_text(
        "import tensorflow as tf  # must never execute on host\n"
        "RAISED = True\n"
        + extra_nodes_py,
        encoding="utf-8",
    )
    return d


def _mock_ensure(plugin_name, requirements, **kwargs):
    return Path("/tmp/fake-venv/bin/python")


def test_isolated_loader_ensure_includes_optional_deps(
    tmp_path: Path, fresh_registry, monkeypatch
) -> None:
    """Isolated venvs get optional ML extras (mocked; never pip-installs TF)."""
    monkeypatch.delenv("GRAPHYN_ISOLATED_INSTALL_TORCH", raising=False)
    extra_toml = """
dependencies = ["numpy>=1.24"]
optional_dependencies = [
    "tensorflow>=2.13",
    "keras>=3.0",
    "torch>=2.0",
]
"""
    plugin_dir = _isolated_toml(tmp_path, extra_toml=extra_toml)
    captured: dict = {}

    def capture_ensure(plugin_name, requirements, **kwargs):
        captured["name"] = plugin_name
        captured["reqs"] = list(requirements)
        return Path("/tmp/fake-venv/bin/python")

    loader = PluginLoader(fresh_registry)
    with patch.object(_VenvMgr, "ensure", side_effect=capture_ensure):
        loader.load(plugin_dir)
    try:
        assert captured["name"] == "iso-plugin"
        assert "numpy>=1.24" in captured["reqs"]
        assert "tensorflow>=2.13" in captured["reqs"]
        assert "keras>=3.0" in captured["reqs"]
        # torch is optional unless GRAPHYN_ISOLATED_INSTALL_TORCH=1
        assert not any(
            r.split("[")[0].split(">")[0].split("=")[0].strip().lower() == "torch"
            for r in captured["reqs"]
        )
    finally:
        get_runtime_registry().unregister_plugin("iso-plugin")


def test_isolated_venv_requirements_torch_env(monkeypatch) -> None:
    monkeypatch.setenv("GRAPHYN_ISOLATED_INSTALL_TORCH", "1")
    m = PluginManifest(
        name="trainer",
        version="1.0.0",
        description="demo",
        author="t",
        platform_version=">=0.0",
        entry_points=["nodes.py"],
        runtime="isolated",
        dependencies=["numpy>=1.24"],
        optional_dependencies=["tensorflow>=2.13", "keras>=3.0", "torch>=2.0"],
    )
    reqs = isolated_venv_requirements(m)
    assert "tensorflow>=2.13" in reqs
    assert "keras>=3.0" in reqs
    assert "torch>=2.0" in reqs


def test_isolated_loader_does_not_exec_entry_point(tmp_path: Path, fresh_registry) -> None:
    """B2: host must not import isolated plugin third-party stacks."""
    plugin_dir = _isolated_toml(tmp_path)
    loader = PluginLoader(fresh_registry)
    with patch.object(_VenvMgr, "ensure", side_effect=_mock_ensure):
        types = loader.load(plugin_dir)
    try:
        assert "iso_node" in types
        cls = fresh_registry.get_class("iso_node")
        assert getattr(cls, "_graphyn_isolated", False) is True
        source = (plugin_dir / "nodes.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        # File still contains the tensorflow import — we just did not execute it.
        assert any(
            isinstance(n, ast.Import) and any(a.name == "tensorflow" for a in n.names)
            for n in tree.body
        )
    finally:
        get_runtime_registry().unregister_plugin("iso-plugin")


def test_isolated_loader_ast_fallback_without_manifest_node_types(
    tmp_path: Path, fresh_registry
) -> None:
    d = tmp_path / "ast-iso"
    d.mkdir()
    (d / "plugin.toml").write_text(
        '''\
[plugin]
name = "ast-iso"
version = "1.0.0"
description = "ast fallback"
author = "t"
platform_version = ">=0.0"
entry_points = ["nodes.py"]
runtime = "isolated"
''',
        encoding="utf-8",
    )
    (d / "nodes.py").write_text(
        "import tensorflow\n"
        "from typing import ClassVar\n"
        "class N:\n"
        '    node_type: ClassVar[str] = "ast_extracted"\n',
        encoding="utf-8",
    )
    loader = PluginLoader(fresh_registry)
    with patch.object(_VenvMgr, "ensure", side_effect=_mock_ensure):
        types = loader.load(d)
    try:
        assert types == ["ast_extracted"]
    finally:
        get_runtime_registry().unregister_plugin("ast-iso")


def test_isolated_setup_skipped_on_host(tmp_path: Path, fresh_registry) -> None:
    """B1: NodeExecutor.setup() must not call isolated node.setup() on the host."""
    plugin_dir = _isolated_toml(tmp_path)
    loader = PluginLoader(fresh_registry)
    with patch.object(_VenvMgr, "ensure", side_effect=_mock_ensure):
        loader.load(plugin_dir)
    cls = fresh_registry.get_class("iso_node")
    setup_called = {"n": 0}

    def boom_setup(self):
        setup_called["n"] += 1
        raise AssertionError("host setup must not run for isolated nodes")

    try:
        cls.setup = boom_setup
        node = cls()
        ex = NodeExecutor(node)
        ex.setup()
        assert setup_called["n"] == 0
        assert ex._setup_done is True
    finally:
        get_runtime_registry().unregister_plugin("iso-plugin")


def test_isolated_process_fail_closed_without_spec(fresh_registry) -> None:
    """H1: isolated types never silently fall back to in-process process()."""

    class Marked(Node):
        node_type: ClassVar[str] = "ghost_iso"
        input_ports: ClassVar[dict] = {}
        output_ports: ClassVar[dict] = {}
        metadata: ClassVar[NodeMetadata] = NodeMetadata(
            node_type="ghost_iso",
            label="Ghost",
            description="x",
            category="test",
        )
        _graphyn_isolated = True

        def process(self, inputs):
            return {"ran": "in-process"}

    node = Marked()
    ex = NodeExecutor(node)
    with pytest.raises(RuntimeError, match="refusing in-process fallback"):
        ex._process(node, {})


def test_isolated_process_uses_worker_not_host(fresh_registry) -> None:
    spec = IsolatedPluginSpec(
        plugin_name="iso-plugin",
        install_path="/tmp/iso",
        venv_python="/tmp/venv/bin/python",
        node_types=("iso_node",),
    )
    get_runtime_registry().register(spec)
    try:

        class Marked(Node):
            node_type: ClassVar[str] = "iso_node"
            input_ports: ClassVar[dict] = {}
            output_ports: ClassVar[dict] = {}
            metadata: ClassVar[NodeMetadata] = NodeMetadata(
                node_type="iso_node",
                label="Iso",
                description="x",
                category="test",
            )
            _graphyn_isolated = True

            def process(self, inputs):
                raise AssertionError("host process must not run")

        node = Marked()
        ex = NodeExecutor(node)
        with patch(
            "app.core.plugins.isolated_executor.run_isolated_node",
            return_value={"ok": True},
        ) as run:
            out = ex._process(node, {"a": 1})
        assert out == {"ok": True}
        run.assert_called_once()
        assert run.call_args.kwargs["node_type"] == "iso_node"
    finally:
        get_runtime_registry().unregister_plugin("iso-plugin")


def test_isolated_lookup_error_fail_closed(monkeypatch) -> None:
    class Marked(Node):
        node_type: ClassVar[str] = "iso_err"
        input_ports: ClassVar[dict] = {}
        output_ports: ClassVar[dict] = {}
        metadata: ClassVar[NodeMetadata] = NodeMetadata(
            node_type="iso_err",
            label="Iso",
            description="x",
            category="test",
        )
        _graphyn_isolated = True

        def process(self, inputs):
            return {"host": True}

    def boom():
        raise ImportError("simulated registry import failure")

    monkeypatch.setattr(
        "app.core.plugins.runtime_registry.get_runtime_registry", boom
    )
    ex = NodeExecutor(Marked())
    with pytest.raises(RuntimeError, match="refusing in-process fallback"):
        ex._process(ex._node, {})


def test_restricted_unpickler_rejects_os_system(tmp_path: Path) -> None:
    """B3: host unpickle of worker results fails closed on unknown globals."""
    import os

    class Evil:
        def __reduce__(self):
            return (os.system, ("true",))

    payload = tmp_path / "out.pkl"
    with payload.open("wb") as fh:
        pickle.dump({"x": Evil()}, fh)
    with pytest.raises(pickle.UnpicklingError):
        load_isolated_outputs(payload)



def test_restricted_unpickler_rejects_keras_functional() -> None:
    """Host must fail-closed on keras worker outputs — never allowlist keras/TF."""
    import io

    from app.core.plugins.isolated_executor import _ALLOWED_PICKLE_MODULES

    assert not any(m == "keras" or m.startswith("keras.") for m in _ALLOWED_PICKLE_MODULES)
    assert not any(m == "tensorflow" or m.startswith("tensorflow.") for m in _ALLOWED_PICKLE_MODULES)

    unpickler = RestrictedUnpickler(io.BytesIO(b""))
    with pytest.raises(pickle.UnpicklingError, match="keras.src.models.functional.Functional"):
        unpickler.find_class("keras.src.models.functional", "Functional")


def test_restricted_unpickler_allows_model_artifact(tmp_path: Path) -> None:
    from app.models.model_artifact import ModelArtifact

    payload = tmp_path / "artifact.pkl"
    art = ModelArtifact(model_path="/tmp/compiled.keras", labels=["yes", "no"])
    with payload.open("wb") as fh:
        pickle.dump({"output": art}, fh)
    out = load_isolated_outputs(payload)
    assert isinstance(out["output"], ModelArtifact)
    assert out["output"].model_path.endswith("compiled.keras")
    assert out["output"].labels == ["yes", "no"]


def test_restricted_unpickler_allows_dict_and_numpy(tmp_path: Path) -> None:
    import numpy as np

    payload = tmp_path / "out.pkl"
    with payload.open("wb") as fh:
        pickle.dump({"arr": np.array([1, 2, 3]), "n": 3}, fh)
    out = load_isolated_outputs(payload)
    assert out["n"] == 3
    assert list(out["arr"]) == [1, 2, 3]


def _fake_plugin_dataset_artifact_class():
    """DatasetArtifact whose __module__ mimics a dynamically loaded plugin."""
    from app.models.dataset_artifact import DatasetArtifact

    module_name = "_graphyn_plugin_dataset_builder_1d6cc092.types"
    return type(DatasetArtifact.__name__, (DatasetArtifact,), {"__module__": module_name})


def test_recast_plugin_dataset_artifact_pickle_roundtrip() -> None:
    """Host plugin-module DatasetArtifact recasts onto app.models and pickles."""
    from app.core.plugins.isolated_executor import recast_plugin_types
    from app.models.dataset_artifact import DatasetArtifact
    from app.models.model_artifact import ModelArtifact

    PluginDA = _fake_plugin_dataset_artifact_class()
    art = PluginDA(
        labels=["yes", "no"],
        n_classes=2,
        input_shape=(4, 2, 1),
        X_train=[[0.0, 1.0, 0.0, 0.0]],
        y_train=[1],
    )
    assert art.__class__.__module__.startswith("_graphyn_plugin_")
    assert art.__class__.__name__ == "DatasetArtifact"

    recast = recast_plugin_types({"dataset": art, "nested": [art]})
    assert recast["dataset"].__class__ is DatasetArtifact
    assert recast["dataset"].__class__.__module__ == "app.models.dataset_artifact"
    assert recast["dataset"].labels == ["yes", "no"]
    assert recast["nested"][0].__class__ is DatasetArtifact

    blob = pickle.dumps(recast)
    loaded = pickle.loads(blob)
    assert isinstance(loaded["dataset"], DatasetArtifact)
    assert loaded["dataset"].n_classes == 2

    # ModelArtifact from a fake plugin module recasts the same way.
    FakeMA = type(
        "ModelArtifact",
        (ModelArtifact,),
        {"__module__": "_graphyn_plugin_trainer_deadbeef.types"},
    )
    recast_ma = recast_plugin_types(FakeMA(model_path="/tmp/m", labels=["a"]))
    assert recast_ma.__class__ is ModelArtifact
    pickle.dumps(recast_ma)


def test_isolated_model_builder_input_pickle_does_not_explode(tmp_path: Path) -> None:
    """run_isolated_node dump of plugin-module DatasetArtifact must succeed."""
    from app.core.plugins import isolated_executor as iso
    from app.models.dataset_artifact import DatasetArtifact

    PluginDA = _fake_plugin_dataset_artifact_class()
    art = PluginDA(labels=["cat"], n_classes=1, input_shape=(2,))
    spec = IsolatedPluginSpec(
        plugin_name="trainer",
        install_path=str(tmp_path),
        venv_python="/bin/true",
        node_types=("model_builder", "trainer"),
    )
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        job_path = Path(cmd[-1])
        inputs_path = job_path.parent / "inputs.pkl"
        with inputs_path.open("rb") as fh:
            loaded = pickle.load(fh)
        captured["inputs"] = loaded
        out_path = job_path.parent / "outputs.pkl"
        with out_path.open("wb") as fh:
            pickle.dump({"ok": True}, fh)
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        m.stdout = ""
        return m

    with patch("app.core.plugins.isolated_executor.subprocess.run", side_effect=fake_run):
        result = iso.run_isolated_node(
            spec,
            node_type="model_builder",
            config={"architecture": "simple_cnn"},
            seed=0,
            inputs={"input": art},
        )
        trainer_result = iso.run_isolated_node(
            spec,
            node_type="trainer",
            config={},
            seed=0,
            inputs={"dataset": art, "model": None},
        )
    assert result == {"ok": True}
    assert trainer_result == {"ok": True}
    dumped = captured["inputs"]["dataset"]
    assert dumped.__class__ is DatasetArtifact
    assert dumped.__class__.__module__ == "app.models.dataset_artifact"
    assert dumped.labels == ["cat"]


def test_disable_unregisters_runtime(tmp_path: Path, fresh_registry) -> None:
    """H2: disable() must unregister_plugin on PluginRuntimeRegistry."""
    spec = IsolatedPluginSpec(
        plugin_name="dis-plugin",
        install_path=str(tmp_path / "dis-plugin"),
        venv_python="/tmp/venv/bin/python",
        node_types=("dis_node",),
    )
    get_runtime_registry().register(spec)
    (tmp_path / "dis-plugin").mkdir()
    rec = PluginRecord(
        name="dis-plugin",
        version="1.0.0",
        source="local",
        install_path=str(tmp_path / "dis-plugin"),
        enabled=True,
        installed_at="2026-01-01T00:00:00+00:00",
        manifest={"name": "dis-plugin", "runtime": "isolated", "node_types": ["dis_node"]},
    )
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_path))
    mgr._store.save(rec)
    assert get_runtime_registry().get_for_node("dis_node") is spec
    mgr.disable("dis-plugin")
    assert get_runtime_registry().get_for_node("dis_node") is None
    assert get_runtime_registry().get_for_plugin("dis-plugin") is None


def test_isolated_venv_default_no_system_site_packages() -> None:
    """H3: isolated venvs must not inherit host site-packages by default."""
    import inspect

    src = inspect.getsource(PluginVenvManager.ensure)
    assert "system_site_packages: bool = False" in src or (
        "system_site_packages: bool = False" in inspect.getsource(_VenvMgr.ensure)
    )


def test_allowlist_applies_to_index_download_url(monkeypatch) -> None:
    """H4: when allowlist is set, index download_url must be checked."""
    monkeypatch.setenv("GRAPHYN_PLUGIN_ALLOWED_SOURCES", "https://allowed.example/")
    installer = PluginInstaller()
    entry = MagicMock()
    entry.download_url = "https://evil.example/p.zip"
    entry.checksum = None
    installer._index_client = MagicMock()
    installer._index_client.lookup.return_value = entry
    with pytest.raises(PluginInstallError, match="allowed sources"):
        installer._resolve_index("plug", None)


def test_allowlist_applies_to_redirect_target(monkeypatch) -> None:
    monkeypatch.setenv("GRAPHYN_PLUGIN_ALLOWED_SOURCES", "https://allowed.example/")
    installer = PluginInstaller()
    hop = MagicMock()
    hop.url = "https://evil.example/p.zip"
    final = MagicMock()
    final.url = "https://evil.example/p.zip"
    final.history = [hop]
    final.raise_for_status = lambda: None
    final.iter_bytes = lambda chunk_size=65536: iter(())

    class _CM:
        def __enter__(self):
            return final

        def __exit__(self, *a):
            return False

    with patch("app.core.plugins.installer.httpx.stream", return_value=_CM()):
        with pytest.raises(PluginInstallError, match="allowed sources"):
            installer._download_with_limit("https://allowed.example/p.zip")


def test_allowlist_applies_to_pep508_url(monkeypatch) -> None:
    monkeypatch.setenv("GRAPHYN_PLUGIN_ALLOWED_SOURCES", "https://allowed.example/")
    with pytest.raises(PluginDependencyError, match="PEP 508 URL"):
        DependencyChecker()._check_requirement_urls(
            ["evil @ https://evil.example/evil.whl"]
        )


def test_allowlist_unset_still_allows_all(monkeypatch) -> None:
    monkeypatch.delenv("GRAPHYN_PLUGIN_ALLOWED_SOURCES", raising=False)
    DependencyChecker()._check_requirement_urls(
        ["evil @ https://evil.example/evil.whl"]
    )


def test_zip_extraction_rejects_symlink(tmp_path: Path) -> None:
    """H5: ZIP extraction must reject symlink members (TAR already does)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("link-to-etc")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
    installer = PluginInstaller()
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(PluginInstallError, match="symlink"):
        installer._extract_archive_bytes(buf.getvalue(), "mem.zip", dest)


def test_isolated_worker_timeout_is_finite(monkeypatch, tmp_path: Path) -> None:
    """H6: isolated worker subprocess.run timeout must be finite."""
    from app.core.config import plugin_isolated_timeout
    from app.core.plugins import isolated_executor as iso

    monkeypatch.setenv("GRAPHYN_PLUGIN_ISOLATED_TIMEOUT", "12")
    assert plugin_isolated_timeout() == 12.0

    spec = IsolatedPluginSpec(
        plugin_name="t",
        install_path=str(tmp_path),
        venv_python="/bin/true",
        node_types=("t",),
    )
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        # Worker writes outputs.pkl; emulate that next to job.json path.
        job_path = Path(cmd[-1])
        out_path = job_path.parent / "outputs.pkl"
        with out_path.open("wb") as fh:
            pickle.dump({"ok": True}, fh)
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        m.stdout = ""
        return m

    with patch("app.core.plugins.isolated_executor.subprocess.run", side_effect=fake_run):
        result = iso.run_isolated_node(
            spec, node_type="t", config={}, seed=1, inputs={}, timeout=None
        )
    assert result == {"ok": True}
    assert captured["timeout"] == 12.0


def test_venv_manager_create_and_gc_no_pip_install(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.core.plugins.venv_manager.DependencyChecker._find_unsatisfied",
        lambda self, parsed, python=None: [],
    )
    monkeypatch.setattr(
        "app.core.plugins.venv_manager.DependencyChecker.install",
        lambda *a, **k: None,
    )
    mgr = PluginVenvManager(base_dir=tmp_path)
    py = mgr.ensure("tiny-plugin", ["pip"])
    assert Path(py).exists()
    removed = mgr.gc_unused(set())
    assert "tiny-plugin" in removed

def test_isolated_stub_exposes_ast_config_schema(tmp_path: Path, fresh_registry) -> None:
    """Isolated stubs must accept real Config fields instead of extra_forbidden."""
    extra = """
from typing import ClassVar
from app.core.nodes.config import NodeConfig
from app.core.nodes.ports import InputPort, OutputPort

class ModelBuilderNode:
    node_type: ClassVar[str] = "iso_node"
    input_ports = {
        "input": InputPort(name="input", data_type=object, required=True),
    }
    output_ports = {
        "output": OutputPort(name="output", data_type=object),
    }
    class Config(NodeConfig):
        architecture: str = "ds_cnn"
        filters: int = 64
        num_layers: int = 4
        dropout_rate: float = 0.25
        learning_rate: float = 0.001
        backend: str = "auto"
"""
    plugin_dir = _isolated_toml(tmp_path, extra_nodes_py=extra)
    loader = PluginLoader(fresh_registry)
    with patch.object(_VenvMgr, "ensure", side_effect=_mock_ensure):
        loader.load(plugin_dir)
    try:
        cls = fresh_registry.get_class("iso_node")
        cfg = cls.Config.model_validate({
            "architecture": "ds_cnn",
            "filters": 64,
            "num_layers": 4,
            "dropout_rate": 0.25,
            "learning_rate": 0.001,
            "backend": "keras",
        })
        assert cfg.architecture == "ds_cnn"
        assert "input" in cls.input_ports
        assert "output" in cls.output_ports
        import pydantic
        with pytest.raises(pydantic.ValidationError) as ei:
            cls.Config.model_validate({"not_a_real_field": 1})
        assert any(e["type"] == "extra_forbidden" for e in ei.value.errors())
    finally:
        get_runtime_registry().unregister_plugin("iso-plugin")


def test_isolated_stub_config_schema_from_toml(tmp_path: Path, fresh_registry) -> None:
    """plugin.toml config_schema is used when AST has no Config class."""
    extra_toml = """
[config_schema.iso_node]
architecture = { type = "string", default = "ds_cnn" }
filters = { type = "integer", default = 64 }
"""
    plugin_dir = _isolated_toml(tmp_path, extra_toml=extra_toml)
    loader = PluginLoader(fresh_registry)
    with patch.object(_VenvMgr, "ensure", side_effect=_mock_ensure):
        loader.load(plugin_dir)
    try:
        cls = fresh_registry.get_class("iso_node")
        cfg = cls.Config.model_validate({"architecture": "mobilenet", "filters": 32})
        assert cfg.architecture == "mobilenet"
        assert cfg.filters == 32
    finally:
        get_runtime_registry().unregister_plugin("iso-plugin")
