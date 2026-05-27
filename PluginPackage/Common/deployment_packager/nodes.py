"""DeploymentPackagerNode — bundle optimized models into deployment-ready packages.

Targets:
    mobile  — ZIP with .tflite/.onnx + labels.txt + metadata.json + inference snippet
    mcu     — C header file with model as byte array + labels array
    docker  — Dockerfile + model + FastAPI inference server script
    edge    — TAR with model + run_inference.py + requirements.txt

Absorbs: export.py, file_export.py, hf_export.py
"""
from __future__ import annotations

import copy
import json
import logging
import os
import tarfile
import zipfile
from pathlib import Path
from typing import ClassVar

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.deployment_artifact import DeploymentArtifact

log = logging.getLogger(__name__)

# ── inference snippet templates ───────────────────────────────────────────────

_ANDROID_SNIPPET = """\
// Android TFLite inference snippet
// Add to your Activity or ViewModel
import org.tensorflow.lite.Interpreter;
import java.nio.ByteBuffer;

Interpreter tflite = new Interpreter(loadModelFile(context, "model.tflite"));
float[][] output = new float[1][NUM_CLASSES];
tflite.run(inputBuffer, output);
"""

_PYTHON_INFERENCE = """\
#!/usr/bin/env python3
\"\"\"Minimal inference script for edge deployment.\"\"\"
import numpy as np
import json
from pathlib import Path

def load_labels(path):
    return Path(path).read_text().strip().splitlines()

def run_tflite(model_path, input_data, labels_path):
    import tflite_runtime.interpreter as tflite
    interp = tflite.Interpreter(model_path=model_path)
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]
    interp.set_tensor(inp['index'], input_data.astype(inp['dtype']))
    interp.invoke()
    probs = interp.get_tensor(out['index'])[0]
    labels = load_labels(labels_path)
    return labels[np.argmax(probs)], float(np.max(probs))

if __name__ == "__main__":
    import sys
    model_path = sys.argv[1] if len(sys.argv) > 1 else "model.tflite"
    labels_path = sys.argv[2] if len(sys.argv) > 2 else "labels.txt"
    # Replace with your actual input preprocessing
    dummy_input = np.zeros((1, 101, 40, 1), dtype=np.float32)
    label, confidence = run_tflite(model_path, dummy_input, labels_path)
    print(f"Predicted: {label} ({confidence:.3f})")
"""

_DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
"""

_FASTAPI_SERVER = """\
#!/usr/bin/env python3
\"\"\"FastAPI inference server for edge deployment.\"\"\"
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import numpy as np
import json
from pathlib import Path

app = FastAPI(title="Audio Inference Server")

class InferenceRequest(BaseModel):
    features: list  # flat list of float32 values

@app.post("/predict")
def predict(req: InferenceRequest):
    try:
        import tflite_runtime.interpreter as tflite
        interp = tflite.Interpreter(model_path="model.tflite")
        interp.allocate_tensors()
        inp_detail = interp.get_input_details()[0]
        out_detail = interp.get_output_details()[0]
        shape = inp_detail['shape']
        data = np.array(req.features, dtype=np.float32).reshape(shape)
        interp.set_tensor(inp_detail['index'], data)
        interp.invoke()
        probs = interp.get_tensor(out_detail['index'])[0].tolist()
        labels = Path("labels.txt").read_text().strip().splitlines()
        top_idx = int(np.argmax(probs))
        return {"label": labels[top_idx], "confidence": probs[top_idx], "all_probs": probs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
"""

_REQUIREMENTS_TXT = """\
tflite-runtime>=2.14
fastapi>=0.100
uvicorn>=0.23
numpy>=1.24
"""


class DeploymentPackagerNode(Node):
    """Bundle optimized models into deployment-ready packages.

    Config:
        target (str): "mobile" | "mcu" | "docker" | "edge"
        output_path (str): directory for output packages
        include_inference_script (bool): include inference script in package
        include_metadata (bool): include metadata.json in package
        package_name (str): base name for the output file (auto-derived if empty)
    """

    node_type: ClassVar[str] = "deployment_packager"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="deployment_packager",
        label="Deployment Packager",
        description=(
            "Bundle optimized models into deployment-ready packages: "
            "mobile ZIP, MCU C header, Docker image, or edge TAR."
        ),
        category="ML",
        version="1.0.0",
        tags=["ml", "deployment", "packaging", "tflite", "docker", "edge", "mcu"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=DeploymentArtifact,
            cardinality="single",
            required=True,
            description="DeploymentArtifact from edge_optimizer",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=DeploymentArtifact,
            description="DeploymentArtifact with artifact_path pointing to the package",
        )
    }

    class Config(NodeConfig):
        target: str = "mobile"          # "mobile" | "mcu" | "docker" | "edge"
        output_path: str = "workspace/artifacts/packages"
        include_inference_script: bool = True
        include_metadata: bool = True
        package_name: str = ""          # auto-derived from model_format + target if empty

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, artifact: DeploymentArtifact) -> DeploymentArtifact:
        target = self.config.target
        out_dir = Path(self.config.output_path)
        out_dir.mkdir(parents=True, exist_ok=True)

        model_path = Path(artifact.artifact_path) if artifact.artifact_path else None
        labels = getattr(artifact, "labels", None) or []
        pkg_name = self.config.package_name or f"model_{target}"

        if target == "mobile":
            pkg_path = self._package_mobile(model_path, labels, artifact, out_dir, pkg_name)
        elif target == "mcu":
            pkg_path = self._package_mcu(model_path, labels, out_dir, pkg_name)
        elif target == "docker":
            pkg_path = self._package_docker(model_path, labels, artifact, out_dir, pkg_name)
        elif target == "edge":
            pkg_path = self._package_edge(model_path, labels, artifact, out_dir, pkg_name)
        else:
            raise ValueError(
                f"DeploymentPackagerNode: unknown target '{target}'. "
                "Choose from: mobile, mcu, docker, edge"
            )

        new_meta = dict(artifact.metadata)
        new_meta["packager"] = {
            "target": target,
            "package_path": str(pkg_path),
            "include_inference_script": self.config.include_inference_script,
        }
        try:
            result = artifact.model_copy(update={
                "artifact_path": str(pkg_path),
                "metadata": new_meta,
            })
        except Exception:
            result = copy.deepcopy(artifact)
            result.artifact_path = str(pkg_path)
            result.metadata = new_meta
        log.info("DeploymentPackagerNode: packaged → %s", pkg_path)
        return result

    # ── mobile package ────────────────────────────────────────────────────────

    def _package_mobile(self, model_path, labels, artifact, out_dir, name) -> Path:
        zip_path = out_dir / f"{name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if model_path and model_path.exists():
                zf.write(model_path, model_path.name)
            # labels.txt
            zf.writestr("labels.txt", "\n".join(labels))
            # metadata.json
            if self.config.include_metadata:
                meta = {
                    "model_format": artifact.model_format,
                    "target_hardware": artifact.target_hardware,
                    "quantization": artifact.quantization,
                    "n_classes": len(labels),
                    "labels": labels,
                }
                zf.writestr("metadata.json", json.dumps(meta, indent=2))
            # inference snippet
            if self.config.include_inference_script:
                zf.writestr("inference_android.java", _ANDROID_SNIPPET)
        return zip_path

    # ── MCU package ───────────────────────────────────────────────────────────

    def _package_mcu(self, model_path, labels, out_dir, name) -> Path:
        header_path = out_dir / f"{name}.h"
        model_bytes = b""
        if model_path and model_path.exists():
            model_bytes = model_path.read_bytes()

        label_strs = ", ".join(f'"{lbl}"' for lbl in labels)
        model_name = model_path.name if model_path else "model"

        # Write header incrementally to avoid building a ~50 MB string in RAM
        # for large models (5–10 MB TFLite files → ~50 MB hex representation).
        with open(header_path, "w") as fh:
            fh.write(
                f"/* Auto-generated MCU deployment header */\n"
                f"#pragma once\n"
                f"#include <stdint.h>\n\n"
                f"/* Model: {model_name} */\n"
                f"/* Size: {len(model_bytes)} bytes */\n"
                f"static const uint8_t g_model_data[] = {{"
            )
            for i, b in enumerate(model_bytes):
                fh.write(f"0x{b:02x}")
                if i < len(model_bytes) - 1:
                    fh.write(", ")
            fh.write(
                f"}};\n"
                f"static const int g_model_data_len = {len(model_bytes)};\n\n"
                f"/* Labels */\n"
                f"static const char* g_labels[] = {{{label_strs}}};\n"
                f"static const int g_num_labels = {len(labels)};\n"
            )
        return header_path

    # ── Docker package ────────────────────────────────────────────────────────

    def _package_docker(self, model_path, labels, artifact, out_dir, name) -> Path:
        import shutil
        pkg_dir = out_dir / name
        pkg_dir.mkdir(exist_ok=True)

        try:
            if model_path and model_path.exists():
                shutil.copy2(model_path, pkg_dir / model_path.name)

            (pkg_dir / "labels.txt").write_text("\n".join(labels))
            (pkg_dir / "Dockerfile").write_text(_DOCKERFILE)
            (pkg_dir / "requirements.txt").write_text(_REQUIREMENTS_TXT)

            if self.config.include_inference_script:
                (pkg_dir / "server.py").write_text(_FASTAPI_SERVER)

            if self.config.include_metadata:
                meta = {
                    "model_format": artifact.model_format,
                    "target_hardware": artifact.target_hardware,
                    "quantization": artifact.quantization,
                    "labels": labels,
                }
                (pkg_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

            # Create TAR of the docker context — write to tmp then rename atomically
            tar_path = out_dir / f"{name}_docker.tar.gz"
            tmp_tar = tar_path.with_suffix(".tmp.tar.gz")
            try:
                with tarfile.open(tmp_tar, "w:gz") as tf:
                    tf.add(pkg_dir, arcname=name)
                os.replace(tmp_tar, tar_path)
            finally:
                if tmp_tar.exists():
                    tmp_tar.unlink(missing_ok=True)
        finally:
            # Clean up the uncompressed staging directory
            shutil.rmtree(pkg_dir, ignore_errors=True)

        return tar_path

    # ── edge package ──────────────────────────────────────────────────────────

    def _package_edge(self, model_path, labels, artifact, out_dir, name) -> Path:
        tar_path = out_dir / f"{name}_edge.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            if model_path and model_path.exists():
                tf.add(model_path, arcname=model_path.name)

            # Add labels.txt
            import io
            labels_bytes = "\n".join(labels).encode()
            info = tarfile.TarInfo(name="labels.txt")
            info.size = len(labels_bytes)
            tf.addfile(info, io.BytesIO(labels_bytes))

            # Add inference script
            if self.config.include_inference_script:
                script_bytes = _PYTHON_INFERENCE.encode()
                info2 = tarfile.TarInfo(name="run_inference.py")
                info2.size = len(script_bytes)
                tf.addfile(info2, io.BytesIO(script_bytes))

            # Add requirements.txt
            req_bytes = _REQUIREMENTS_TXT.encode()
            info3 = tarfile.TarInfo(name="requirements.txt")
            info3.size = len(req_bytes)
            tf.addfile(info3, io.BytesIO(req_bytes))

            # Add metadata.json
            if self.config.include_metadata:
                meta = {
                    "model_format": artifact.model_format,
                    "target_hardware": artifact.target_hardware,
                    "quantization": artifact.quantization,
                    "labels": labels,
                }
                meta_bytes = json.dumps(meta, indent=2).encode()
                info4 = tarfile.TarInfo(name="metadata.json")
                info4.size = len(meta_bytes)
                tf.addfile(info4, io.BytesIO(meta_bytes))

        return tar_path
