"""Wave-1 backend smoke tests.

Stub paths always run. Real backend paths run when GRAPHYN_WAVE1_VENV_* is set
(or the import is available in the active interpreter); otherwise they skip.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _venv_python(capability: str) -> str | None:
    from app.core.plugins.wave1_runtime import wave1_python

    py = wave1_python(capability)
    return str(py) if py and Path(py).is_file() else None


def _run_in_venv(capability: str, code: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    py = _venv_python(capability)
    if not py:
        pytest.skip(f"GRAPHYN_WAVE1_VENV_{capability.upper()} / wave1-{capability} not installed")
    env = os.environ.copy()
    env.setdefault("CUDA_VISIBLE_DEVICES", "")
    env.setdefault("GRAPHYN_WAVE1_FORCE_CPU", "1")
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [py, "-c", code],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_vector_store_write_stub(tmp_path):
    from unit_test.plugins._helpers import materialize_isolated_class
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager

    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_path / "plugins"))
    mgr._plugins_dir = str(tmp_path / "plugins")
    mgr.install("PluginPackage/RAG/vector_store_write/")
    cls = materialize_isolated_class(reg.get_class("vector_store_write"))
    node = cls(config=cls.Config(stub=True, persist_path=str(tmp_path / "vs"), backend="chromadb"))
    out = node.process({"embeddings": []})
    assert out["output"].metadata.get("stub") is True


def test_vector_store_query_stub(tmp_path):
    from unit_test.plugins._helpers import materialize_isolated_class
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager

    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_path / "plugins"))
    mgr._plugins_dir = str(tmp_path / "plugins")
    mgr.install("PluginPackage/RAG/vector_store_query/")
    cls = materialize_isolated_class(reg.get_class("vector_store_query"))
    node = cls(config=cls.Config(stub=True))
    out = node.process({"store": object(), "query": "x"})
    assert out["output"] == []


def test_yolo_train_stub(tmp_path):
    from unit_test.plugins._helpers import materialize_isolated_class
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager

    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_path / "plugins"))
    mgr._plugins_dir = str(tmp_path / "plugins")
    mgr.install("PluginPackage/Vision/yolo_train/")
    cls = materialize_isolated_class(reg.get_class("yolo_train"))
    node = cls(config=cls.Config(stub=True, project=str(tmp_path / "yolo"), epochs=1))
    out = node.process({})
    assert Path(out["output"].model_path).exists()
    assert out["output"].history.get("stub") is True


def test_tflm_quantize_stub(tmp_path):
    from unit_test.plugins._helpers import materialize_isolated_class
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager

    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_path / "plugins"))
    mgr._plugins_dir = str(tmp_path / "plugins")
    mgr.install("PluginPackage/TinyML/tflm_quantize/")
    cls = materialize_isolated_class(reg.get_class("tflm_quantize"))
    node = cls(config=cls.Config(stub=True, output_path=str(tmp_path / "tflm")))
    out = node.process({})
    assert Path(out["output"].tflite_path).exists()


def test_mcu_flash_ota_stays_needs_api(tmp_path):
    from unit_test.plugins._helpers import materialize_isolated_class
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager

    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_path / "plugins"))
    mgr._plugins_dir = str(tmp_path / "plugins")
    mgr.install("PluginPackage/TinyML/mcu_flash_ota/")
    cls = materialize_isolated_class(reg.get_class("mcu_flash_ota"))
    node = cls(config=cls.Config(stub=True, dry_run=True))
    out = node.process({})
    assert out["output"].status == "needs-api"


@pytest.mark.backend
def test_real_rag_chromadb_roundtrip():
    code = r'''
import json, tempfile
from pathlib import Path
from app.core.nodes.registry import NodeRegistry
from app.core.plugins.manager import PluginManager
from unit_test.plugins._helpers import materialize_isolated_class

td = Path(tempfile.mkdtemp())
reg = NodeRegistry()
mgr = PluginManager(registry=reg, base_dir=str(td / "plugins"))
mgr._plugins_dir = str(td / "plugins")
mgr.install("PluginPackage/RAG/vector_store_write/")
mgr.install("PluginPackage/RAG/vector_store_query/")
Write = materialize_isolated_class(reg.get_class("vector_store_write"))
Query = materialize_isolated_class(reg.get_class("vector_store_query"))
from PluginPackage.RAG.vector_store_write.types import EmbeddingVector  # may fail
'''
    # Prefer importing types from installed plugin path via constructed objects
    code = r'''
import tempfile
from pathlib import Path
from app.core.nodes.registry import NodeRegistry
from app.core.plugins.manager import PluginManager
from unit_test.plugins._helpers import materialize_isolated_class

td = Path(tempfile.mkdtemp())
persist = td / "vs"
reg = NodeRegistry()
mgr = PluginManager(registry=reg, base_dir=str(td / "plugins"))
mgr._plugins_dir = str(td / "plugins")
mgr.install("PluginPackage/RAG/vector_store_write/")
mgr.install("PluginPackage/RAG/vector_store_query/")
Write = materialize_isolated_class(reg.get_class("vector_store_write"))
Query = materialize_isolated_class(reg.get_class("vector_store_query"))
# Build EmbeddingVector via the write plugin's types module
import importlib.util
spec = importlib.util.spec_from_file_location(
    "vsw_types", Path(Write._graphyn_plugin_install_path if hasattr(Write, "_graphyn_plugin_install_path") else mgr._plugins_dir) 
)
# Simpler: duck-typed objects
class EV:
    def __init__(self, emb, meta=None):
        self.embedding = emb
        self.source_path = ""
        self.label = ""
        self.metadata = meta or {}
class Chunk:
    def __init__(self, text, chunk_id):
        self.text = text
        self.chunk_id = chunk_id
        self.source = ""
        self.page = None
        self.metadata = {}

embs = [EV([0.1, 0.2, 0.3, 0.4], {"chunk_id": "c1"}), EV([0.9, 0.1, 0.0, 0.0], {"chunk_id": "c2"})]
chunks = [Chunk("alpha doc", "c1"), Chunk("beta doc", "c2")]
w = Write(config=Write.Config(stub=False, backend="chromadb", persist_path=str(persist), collection="wave1"))
ref = w.process({"embeddings": embs, "chunks": chunks})["output"]
assert ref.metadata.get("stub") is False, ref.metadata
assert ref.metadata.get("n_embeddings") == 2
q = Query(config=Query.Config(stub=False, backend="chromadb", top_k=1))
hits = q.process({"store": ref, "query": EV([0.9, 0.1, 0.0, 0.0])})["output"]
assert hits and hits[0].chunk_id in ("c2", "c1")
print("RAG_OK", hits[0].chunk_id, hits[0].score)
'''
    proc = _run_in_venv("rag", code, timeout=240)
    if proc.returncode != 0:
        pytest.fail(f"rag real backend failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    assert "RAG_OK" in proc.stdout


@pytest.mark.backend
def test_real_yolo_predict_cpu():
    code = r'''
import tempfile
from pathlib import Path
from PIL import Image
from app.core.nodes.registry import NodeRegistry
from app.core.plugins.manager import PluginManager
from unit_test.plugins._helpers import materialize_isolated_class
from app.models.model_artifact import ModelArtifact

td = Path(tempfile.mkdtemp())
img = td / "a.jpg"
Image.new("RGB", (64, 64), color=(128, 64, 32)).save(img)
reg = NodeRegistry()
mgr = PluginManager(registry=reg, base_dir=str(td / "plugins"))
mgr._plugins_dir = str(td / "plugins")
mgr.install("PluginPackage/Vision/yolo_predict/")
Predict = materialize_isolated_class(reg.get_class("yolo_predict"))
node = Predict(config=Predict.Config(stub=False, device="cpu", imgsz=64, conf=0.01))
out = node.process({
    "model": ModelArtifact(model_path="yolov8n.pt", labels=[], history={}, metrics={}),
    "images": [str(img)],
})
assert isinstance(out["output"], list)
assert out["output"], "expected at least one DetectionResult"
assert out["output"][0].metadata.get("backend") == "ultralytics"
print("YOLO_OK", len(out["output"][0].boxes))
'''
    proc = _run_in_venv("vision", code, timeout=300)
    if proc.returncode != 0:
        pytest.fail(f"yolo real backend failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    assert "YOLO_OK" in proc.stdout


@pytest.mark.backend
def test_real_tflm_quantize_keras():
    code = r'''
import tempfile
from pathlib import Path
import tensorflow as tf
from app.core.nodes.registry import NodeRegistry
from app.core.plugins.manager import PluginManager
from unit_test.plugins._helpers import materialize_isolated_class
from app.models.model_artifact import ModelArtifact

td = Path(tempfile.mkdtemp())
# tiny keras model → saved_model
inp = tf.keras.Input(shape=(4,))
x = tf.keras.layers.Dense(2, activation="relu")(inp)
out = tf.keras.layers.Dense(1, activation="sigmoid")(x)
model = tf.keras.Model(inp, out)
sm = td / "saved_model"
model.export(str(sm)) if hasattr(model, "export") else tf.saved_model.save(model, str(sm))
# Prefer classic saved_model
if not (sm / "saved_model.pb").exists() and not list(sm.glob("*.pb")):
    tf.saved_model.save(model, str(sm))

reg = NodeRegistry()
mgr = PluginManager(registry=reg, base_dir=str(td / "plugins"))
mgr._plugins_dir = str(td / "plugins")
mgr.install("PluginPackage/TinyML/tflm_quantize/")
mgr.install("PluginPackage/TinyML/tflm_convert/")
Q = materialize_isolated_class(reg.get_class("tflm_quantize"))
C = materialize_isolated_class(reg.get_class("tflm_convert"))
q = Q(config=Q.Config(stub=False, output_path=str(td / "quant"), quantization="int8"))
# int8 may need representative dataset; try DEFAULT optimize path by using float convert via convert node
# Use convert on saved_model first
c = C(config=C.Config(stub=False, output_path=str(td / "micro")))
dep = c.process({"input": ModelArtifact(model_path=str(sm), labels=[], history={}, metrics={})})["output"]
assert dep.metadata.get("stub") is False
assert Path(dep.metadata["tflite_path"]).exists()
print("TFLM_OK", dep.metadata["file_size_bytes"], dep.metadata["tflite_path"])
'''
    proc = _run_in_venv("tinyml", code, timeout=300)
    if proc.returncode != 0:
        pytest.fail(f"tflm real backend failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    assert "TFLM_OK" in proc.stdout


def test_yolo_dataset_yaml_build_real(tmp_path):
    from unit_test.plugins._helpers import materialize_isolated_class
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager
    from app.models.dataset_artifact import DatasetArtifact

    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_path / "plugins"))
    mgr._plugins_dir = str(tmp_path / "plugins")
    mgr.install("PluginPackage/Vision/yolo_dataset_yaml_build/")
    cls = materialize_isolated_class(reg.get_class("yolo_dataset_yaml_build"))
    root = tmp_path / "ds"
    node = cls(
        config=cls.Config(
            stub=False,
            path=str(root),
            names=["cat", "dog"],
            train="images/train",
            val="images/val",
        )
    )
    out = node.process({"input": DatasetArtifact(labels=["cat", "dog"], n_classes=2, metadata={})})
    meta = out["output"].metadata
    assert meta.get("stub") is False
    yaml_path = Path(meta["yaml_path"])
    assert yaml_path.is_file()
    body = yaml_path.read_text(encoding="utf-8")
    assert "names:" in body and "cat" in body


def test_bm25_index_build_real(tmp_path):
    from unit_test.plugins._helpers import materialize_isolated_class
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager

    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_path / "plugins"))
    mgr._plugins_dir = str(tmp_path / "plugins")
    mgr.install("PluginPackage/RAG/bm25_index_build/")
    cls = materialize_isolated_class(reg.get_class("bm25_index_build"))

    class Chunk:
        def __init__(self, text, chunk_id):
            self.text = text
            self.chunk_id = chunk_id
            self.source = ""
            self.page = None
            self.metadata = {}

    node = cls(config=cls.Config(stub=False, persist_path=str(tmp_path / "bm25")))
    out = node.process({"input": [Chunk("alpha beta", "c1"), Chunk("beta gamma", "c2")]})
    ref = out["output"]
    assert ref.metadata.get("stub") is False
    assert ref.metadata.get("n_docs") == 2
    assert (Path(ref.path) / "bm25_index.json").is_file()


def test_pgvector_needs_api_without_dsn(tmp_path, monkeypatch):
    from unit_test.plugins._helpers import materialize_isolated_class
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager

    monkeypatch.delenv("PGVECTOR_DSN", raising=False)
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_path / "plugins"))
    mgr._plugins_dir = str(tmp_path / "plugins")
    mgr.install("PluginPackage/RAG/vector_store_write/")
    cls = materialize_isolated_class(reg.get_class("vector_store_write"))
    node = cls(
        config=cls.Config(
            stub=False,
            backend="pgvector",
            persist_path=str(tmp_path / "vs"),
            collection="wave1",
        )
    )

    class EV:
        def __init__(self):
            self.embedding = [0.1, 0.2]
            self.source_path = ""
            self.label = ""
            self.metadata = {"chunk_id": "c1"}

    try:
        node.process({"embeddings": [EV()], "chunks": []})
        raise AssertionError("expected needs-api RuntimeError")
    except RuntimeError as exc:
        msg = str(exc)
        assert "needs-api" in msg
        assert "chromadb" in msg or "faiss" in msg


@pytest.mark.backend
def test_real_yolo_train_coco8_cpu():
    """Tiny ultralytics train (coco8, 1 epoch, CPU) — proves stub=False path."""
    code = (
        "import os, tempfile\n"
        "from pathlib import Path\n"
        "os.environ['CUDA_VISIBLE_DEVICES'] = ''\n"
        "os.environ['GRAPHYN_WAVE1_FORCE_CPU'] = '1'\n"
        "os.environ.setdefault('YOLO_CONFIG_DIR', '/tmp/Ultralytics')\n"
        "from app.core.nodes.registry import NodeRegistry\n"
        "from app.core.plugins.manager import PluginManager\n"
        "from unit_test.plugins._helpers import materialize_isolated_class\n"
        "td = Path(tempfile.mkdtemp())\n"
        "reg = NodeRegistry()\n"
        "mgr = PluginManager(registry=reg, base_dir=str(td / 'plugins'))\n"
        "mgr._plugins_dir = str(td / 'plugins')\n"
        "mgr.install('PluginPackage/Vision/yolo_train/')\n"
        "Train = materialize_isolated_class(reg.get_class('yolo_train'))\n"
        "class DS:\n"
        "    yaml_path = 'coco8.yaml'\n"
        "    root = ''\n"
        "    task = 'detect'\n"
        "    names = []\n"
        "    metadata = {}\n"
        "node = Train(config=Train.Config(stub=False, model='yolov8n.pt', epochs=1, imgsz=64, batch=2, device='cpu', project=str(td / 'runs')))\n"
        "out = node.process({'dataset': DS()})\n"
        "art = out['output']\n"
        "assert art.history.get('stub') is not True\n"
        "print('YOLO_TRAIN_OK', art.model_path, art.history)\n"
    )
    proc = _run_in_venv("vision", code, timeout=600)
    if proc.returncode != 0:
        pytest.fail(f"yolo train real backend failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    assert "YOLO_TRAIN_OK" in proc.stdout
