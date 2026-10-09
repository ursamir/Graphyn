# unit_test/f19/test_f19_edge_targets.py
"""F19 / F-05 — edge export backends and embedded package targets are real.

Before: edge_optimizer ``tflm/executorch/ultralytics_export`` wrote
``BACKEND_STUB.txt`` and deployment_packager ``cmsis_pack/arduino/zephyr/
pte_bundle`` wrote ``PACKAGE_STUB.txt`` and reported success. Now the TFLM /
Arduino / Zephyr / CMSIS-Pack outputs embed the actual model bytes (verified by
compiling the generated C with gcc and reading the bytes back), and the backends
we cannot build (ExecuTorch, Ultralytics) are rejected at config time.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
import yaml

from app.core.ml.embedded_packaging import (
    build_arduino_library,
    build_cmsis_pack,
    build_zephyr_module,
    is_tflite,
    op_resolver_source,
    tflite_operators,
    write_c_model,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "fixtures" / "tiny_int8.tflite"
GCC = shutil.which("gcc")
GXX = shutil.which("g++")
needs_gcc = pytest.mark.skipif(not GCC, reason="gcc not installed")


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod  # pydantic resolves postponed annotations via sys.modules
    spec.loader.exec_module(mod)
    return mod


def _roundtrip_c(tmp: Path, header: Path, source: Path, symbol: str, compiler: str | None = None) -> bytes:
    """Compile the generated source with a tiny main that dumps the array; return the bytes."""
    main = tmp / "dump_main.c"
    main.write_text(
        f'#include <stdio.h>\n#include "{header.name}"\n'
        f"int main(void) {{ fwrite({symbol}, 1, {symbol}_len, stdout);"
        f" fprintf(stderr, \"%d\", {symbol}_num_labels); return 0; }}\n",
        encoding="utf-8",
    )
    exe = tmp / "dump"
    cc = compiler or GCC
    srcs = [str(source)]
    if source.suffix == ".cpp":
        obj = tmp / "model.o"
        subprocess.run([GXX, "-std=c++11", "-Wall", "-Werror", "-c", str(source), "-I", str(header.parent), "-o", str(obj)], check=True)
        srcs = [str(obj)]
        cc = GXX
        main = main.rename(tmp / "dump_main.cpp")
    subprocess.run([cc, "-Wall", "-Werror", "-I", str(header.parent), str(main), *srcs, "-o", str(exe)], check=True)
    out = subprocess.run([str(exe)], check=True, capture_output=True)
    return out.stdout, int(out.stderr.decode())


def test_fixture_is_tflite_and_ops_parsed():
    data = FIXTURE.read_bytes()
    assert is_tflite(FIXTURE)
    assert not is_tflite(Path(__file__))
    assert tflite_operators(data) == [
        "CONV_2D", "SHAPE", "STRIDED_SLICE", "PACK", "RESHAPE", "FULLY_CONNECTED", "SOFTMAX",
    ]
    src, missing = op_resolver_source(data)
    assert missing == []
    assert "MicroMutableOpResolver<7>" in src and "resolver.AddConv2D();" in src
    with pytest.raises(ValueError):
        tflite_operators(b"not a model at all")


@needs_gcc
def test_c_model_compiles_and_holds_exact_bytes(tmp_path):
    data = FIXTURE.read_bytes()
    header, source = write_c_model(data, tmp_path / "c", symbol="g_model", labels=['yes', 'no "q"', "x\\y"])
    text = source.read_text()
    assert "aligned(16)" in text
    got, n_labels = _roundtrip_c(tmp_path, header, source, "g_model")
    assert got == data and n_labels == 3


@needs_gcc
def test_arduino_library_zip(tmp_path):
    z = build_arduino_library(FIXTURE, ["up", "down", "left"], tmp_path, "kws-demo")
    names = set(zipfile.ZipFile(z).namelist())
    assert {
        "kws_demo/library.properties",
        "kws_demo/src/kws_demo.h",
        "kws_demo/src/kws_demo_model_data.h",
        "kws_demo/src/kws_demo_model_data.cpp",
        "kws_demo/src/kws_demo_inference.cpp",
        "kws_demo/examples/kws_demo_classify/kws_demo_classify.ino",
    } <= names
    props = dict(
        line.split("=", 1) for line in (tmp_path / "kws_demo/library.properties").read_text().splitlines() if "=" in line
    )
    assert props["name"] == "kws_demo" and props["includes"] == "kws_demo.h"
    inf = (tmp_path / "kws_demo/src/kws_demo_inference.cpp").read_text()
    assert "MicroMutableOpResolver<7>" in inf and "AllOpsResolver" not in inf
    if GXX:
        root = tmp_path / "kws_demo/src"
        got, n = _roundtrip_c(tmp_path, root / "kws_demo_model_data.h", root / "kws_demo_model_data.cpp", "kws_demo_model")
        assert got == FIXTURE.read_bytes() and n == 3


@needs_gcc
def test_zephyr_module(tmp_path):
    root = build_zephyr_module(FIXTURE, ["a", "b", "c"], tmp_path, "kws")
    mod = yaml.safe_load((root / "zephyr/module.yml").read_text())
    assert mod == {"name": "kws", "build": {"cmake": "zephyr", "kconfig": "zephyr/Kconfig"}}
    cm = (root / "zephyr/CMakeLists.txt").read_text()
    assert "src/kws_model_data.c" in cm and "CONFIG_GRAPHYN_KWS" in cm
    assert "config GRAPHYN_KWS" in (root / "zephyr/Kconfig").read_text()
    got, n = _roundtrip_c(tmp_path, root / "include/kws_model_data.h", root / "src/kws_model_data.c", "kws_model")
    assert got == FIXTURE.read_bytes() and n == 3


@needs_gcc
def test_cmsis_pack_pdsc_and_sources(tmp_path):
    pack = build_cmsis_pack(FIXTURE, ["a", "b", "c"], tmp_path, "Kws", version="1.2.0")
    assert pack.name == "Graphyn.Kws.1.2.0.pack"
    zf = zipfile.ZipFile(pack)
    names = set(zf.namelist())
    pdsc = ET.fromstring(zf.read("Graphyn.Kws.pdsc"))
    assert pdsc.findtext("vendor") == "Graphyn" and pdsc.findtext("name") == "Kws"
    comp = pdsc.find("components/component")
    assert comp.get("Cclass") == "Machine Learning" and comp.get("Cversion") == "1.2.0"
    files = [f.get("name") for f in comp.findall("files/file")]
    for f in files:
        assert f.endswith("/") or f in names, f
    out = tmp_path / "x"
    zf.extractall(out)
    got, n = _roundtrip_c(tmp_path, out / "Include/Kws_model_data.h", out / "Source/Kws_model_data.c", "Kws_model")
    assert got == FIXTURE.read_bytes() and n == 3


# ── deployment_packager node ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def packager():
    return _load("PluginPackage/Common/deployment_packager/nodes.py", "f19_deploy_pkg_nodes")


@pytest.mark.parametrize("target,suffix", [("arduino", ".zip"), ("zephyr", ""), ("cmsis_pack", ".pack")])
def test_packager_embedded_targets(packager, tmp_path, target, suffix):
    from app.models.deployment_artifact import DeploymentArtifact

    model = tmp_path / "model.tflite"
    shutil.copy(FIXTURE, model)
    node = packager.DeploymentPackagerNode(
        config={"target": target, "output_path": str(tmp_path / "pkg"), "package_name": "kws"}, seed=0
    )
    out = node.process({"input": DeploymentArtifact(artifact_path=str(model), model_format="tflite", labels=["a", "b", "c"])})["output"]
    pkg = Path(out.artifact_path)
    assert pkg.exists() and (pkg.suffix == suffix if suffix else pkg.is_dir())
    assert out.metadata["packager"]["target"] == target
    assert not list((tmp_path / "pkg").rglob("*STUB*"))
    payload = b""
    if pkg.suffix in (".zip", ".pack"):
        with zipfile.ZipFile(pkg) as zf:
            payload = b"".join(zf.read(n) for n in zf.namelist() if n.endswith((".c", ".cpp")))
    else:
        payload = b"".join(p.read_bytes() for p in pkg.rglob("*.c"))
    first = ", ".join(f"0x{b:02x}" for b in FIXTURE.read_bytes()[:12])
    assert first.encode() in payload


def test_packager_embedded_targets_need_tflite(packager, tmp_path):
    from app.models.deployment_artifact import DeploymentArtifact

    bogus = tmp_path / "model.onnx"
    bogus.write_bytes(b"\x08\x07onnx-ish")
    node = packager.DeploymentPackagerNode(config={"target": "arduino", "output_path": str(tmp_path)}, seed=0)
    with pytest.raises(ValueError, match="needs a TensorFlow Lite model"):
        node.process({"input": DeploymentArtifact(artifact_path=str(bogus), model_format="onnx")})


def test_packager_mcu_requires_model(packager, tmp_path):
    from app.models.deployment_artifact import DeploymentArtifact

    node = packager.DeploymentPackagerNode(config={"target": "mcu", "output_path": str(tmp_path)}, seed=0)
    with pytest.raises(FileNotFoundError, match="needs a model file"):
        node.process({"input": DeploymentArtifact(artifact_path=str(tmp_path / "missing.tflite"), model_format="tflite")})


def test_packager_pte_bundle_removed(packager):
    with pytest.raises(Exception, match="pte_bundle' was removed"):
        packager.DeploymentPackagerNode(config={"target": "pte_bundle"}, seed=0)


def test_plugin_toml_enums_match():
    import tomllib

    dp = tomllib.loads((ROOT / "PluginPackage/Common/deployment_packager/plugin.toml").read_text())
    eo = tomllib.loads((ROOT / "PluginPackage/Common/edge_optimizer/plugin.toml").read_text())

    def enum(doc, key):
        for sect in ("config_schema", "config"):
            node = doc
            for part in sect.split("."):
                node = node.get(part, {}) if isinstance(node, dict) else {}
            if isinstance(node, dict) and key in node:
                return node[key]["enum"]
        # nested tables like [nodes.x.config_schema]
        stack = [doc]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                if key in cur and isinstance(cur[key], dict) and "enum" in cur[key]:
                    return cur[key]["enum"]
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)
        raise KeyError(key)

    assert enum(dp, "target") == ["mobile", "mcu", "docker", "edge", "cmsis_pack", "arduino", "zephyr"]
    assert enum(eo, "backend") == ["tflite", "onnx", "tflm", "auto"]


# ── edge_optimizer node ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def edge():
    return _load("PluginPackage/Common/edge_optimizer/nodes.py", "f19_edge_nodes")


@pytest.mark.parametrize("backend,needle", [("executorch", "ExecuTorch"), ("ultralytics_export", "vision")])
def test_edge_removed_backends_rejected(edge, backend, needle):
    with pytest.raises(Exception, match=needle):
        edge.EdgeOptimizerNode(config={"backend": backend}, seed=0)


def test_edge_no_stub_code_left():
    src = (ROOT / "PluginPackage/Common/edge_optimizer/nodes.py").read_text()
    assert "BACKEND_STUB" not in src and "_export_stub_backend" not in src
    src = (ROOT / "PluginPackage/Common/deployment_packager/nodes.py").read_text()
    assert "PACKAGE_STUB" not in src and "_package_additive_target" not in src


@needs_gcc
def test_edge_tflm_backend_real_export(edge, tmp_path):
    tf = pytest.importorskip("tensorflow")
    keras = pytest.importorskip("keras")
    import numpy as np
    from app.models.model_artifact import ModelArtifact

    model = keras.Sequential(
        [keras.layers.Input(shape=(4, 2, 1)), keras.layers.Flatten(), keras.layers.Dense(2, activation="softmax")]
    )
    sm = tmp_path / "saved_model"
    try:
        model.export(str(sm))
    except AttributeError:
        tf.saved_model.save(model, str(sm))
    np.save(str(sm / "X_train_repr.npy"), np.zeros((4, 4, 2, 1), dtype=np.float32))
    node = edge.EdgeOptimizerNode(
        config={"backend": "tflm", "quantization": "int8", "output_path": str(tmp_path / "opt")}, seed=0
    )
    out = node.process({"input": ModelArtifact(model_path=str(sm), labels=["a", "b"])})["output"]
    assert out.model_format == "tflm" and out.target_hardware == "mcu"
    tfl = Path(out.artifact_path)
    assert is_tflite(tfl)
    info = out.metadata["tflm"]
    assert "FULLY_CONNECTED" in info["operators"]
    header, source = Path(info["header"]), Path(info["source"])
    got, n = _roundtrip_c(tmp_path, header, source, "g_model")
    assert got == tfl.read_bytes() and n == 2
    assert "resolver.AddFullyConnected();" in Path(info["op_resolver"]).read_text()


@pytest.mark.skipif(
    not (os.environ.get("GRAPHYN_TFLM_ROOT") and GXX),
    reason="set GRAPHYN_TFLM_ROOT to a tflite-micro checkout with gen/*/lib/libtensorflow-microlite.a",
)
def test_arduino_inference_runs_on_real_tflm(tmp_path):
    """Link the generated sketch code against TFLM and compare with the TF interpreter."""
    tf = pytest.importorskip("tensorflow")
    import numpy as np

    t = Path(os.environ["GRAPHYN_TFLM_ROOT"])
    lib = next(t.glob("gen/*/lib/libtensorflow-microlite.a"))
    dl = t / "tensorflow/lite/micro/tools/make/downloads"
    build_arduino_library(FIXTURE, ["a", "b", "c"], tmp_path, "kws")
    (tmp_path / "main.cpp").write_text(
        '#include <cstdio>\n#include <cstdlib>\n#include "kws.h"\n'
        "int main(int c, char** v) { if (kws_model_setup()) return 1; float f[32];"
        " for (int i = 0; i < 32; ++i) f[i] = atof(v[1 + i]);"
        ' printf("%d", kws_model_classify(f, 32)); return 0; }\n'
    )
    src = tmp_path / "kws/src"
    exe = tmp_path / "run"
    subprocess.run(
        [GXX, "-std=c++17", "-DTF_LITE_STATIC_MEMORY", f"-I{t}", f"-I{dl}/flatbuffers/include",
         f"-I{dl}/gemmlowp", f"-I{src}", str(tmp_path / "main.cpp"), str(src / "kws_inference.cpp"),
         str(src / "kws_model_data.cpp"), str(lib), "-o", str(exe)],
        check=True,
    )
    it = tf.lite.Interpreter(model_path=str(FIXTURE))
    it.allocate_tensors()
    i, o = it.get_input_details()[0], it.get_output_details()[0]
    s, zp = i["quantization"]
    rng = np.random.default_rng(0)
    for _ in range(10):
        x = rng.random(32).astype("float32")
        it.set_tensor(i["index"], np.clip(np.round(x / s) + zp, -128, 127).astype(np.int8).reshape(i["shape"]))
        it.invoke()
        ref = int(np.argmax(it.get_tensor(o["index"])[0]))
        got = int(subprocess.run([str(exe), *map(str, x)], capture_output=True, text=True, check=True).stdout)
        assert got == ref
