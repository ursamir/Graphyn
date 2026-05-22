# Node Catalogue

All 29 production nodes live in `PluginPackage/`. There are no built-in node implementations in `app/core/nodes/audio/` or `app/core/nodes/ml/` — those directories have been removed.

For full config fields, port specs, and capability details → **[PluginPackage/NODES.md](../PluginPackage/NODES.md)**  
For architecture, data flow, and install patterns → **[PluginPackage/ARCHITECTURE.md](../PluginPackage/ARCHITECTURE.md)**

---

## Audio Plugins — `PluginPackage/Audio/` (18 nodes)

| node_type | Category | Key Dependencies |
|---|---|---|
| `dataset_ingest` | Input | librosa, soundfile; optional: datasets, boto3 |
| `stream_ingest` | Input | librosa; optional: sounddevice, websockets |
| `audio_conditioner` | Preprocessing | librosa, scipy; optional: pyloudnorm |
| `audio_quality_gate` | Preprocessing | librosa, scipy, numpy; optional: pyloudnorm |
| `audio_annotator` | Preprocessing | numpy (pure Python) |
| `alignment_node` | Preprocessing | optional: ctc-forced-aligner, mfa |
| `segmenter` | Processing | librosa; optional: webrtcvad |
| `augmentation_pipeline` | Augmentation | librosa, scipy; optional: audiomentations |
| `speech_enhancer` | Enhancement | noisereduce; optional: deepfilternet |
| `speaker_separator` | Enhancement | optional: pyannote.audio, speechbrain |
| `environment_simulator` | Enhancement | pyroomacoustics, numpy |
| `feature_frontend` | Features | librosa, numpy |
| `stream_processor` | Streaming | numpy |
| `audio_event_detector` | Detection | optional: tensorflow, torch |
| `audio_classifier` | Inference | optional: tensorflow, torch |
| `speech_synthesizer` | Generation | optional: TTS (Coqui), espeak-ng |
| `voice_converter` | Generation | optional: speechbrain, torch |
| `audio_generator` | Generation | optional: audiocraft, torch |

## Common Plugins — `PluginPackage/Common/` (11 nodes)

| node_type | Category | Key Dependencies |
|---|---|---|
| `dataset_builder` | ML | numpy, scikit-learn; optional: tensorflow, torch |
| `trainer` | ML | optional: tensorflow/keras, torch |
| `evaluator` | ML | scikit-learn, numpy; optional: matplotlib, seaborn |
| `edge_optimizer` | ML | optional: tensorflow, onnx, tf2onnx |
| `realtime_inference` | Inference | optional: tensorflow, torch, onnxruntime |
| `dataset_balancer` | ML | numpy |
| `dataset_versioner` | ML | hashlib, json (stdlib) |
| `experiment_tracker` | ML | json (stdlib); optional: mlflow |
| `deployment_packager` | ML | zipfile, json (stdlib) |
| `embedding_generator` | Features | optional: torch, transformers, openl3, speechbrain |
| `multimodal_fusion` | Features | optional: torch, transformers |

## Capability Matrix

| node_type | GPU Req | Edge | Streaming | Realtime | Deterministic | Cacheable |
|---|---|---|---|---|---|---|
| `dataset_ingest` | No | No | Yes | No | Yes | Yes |
| `stream_ingest` | No | Yes | Yes | Yes | No | No |
| `audio_conditioner` | No | Yes | No | Yes | Yes | Yes |
| `audio_quality_gate` | No | Yes | No | No | Yes | Yes |
| `audio_annotator` | No | Yes | No | No | Yes | Yes |
| `alignment_node` | No | No | No | No | Yes | Yes |
| `segmenter` | No | Yes | Yes | Yes | Yes | Yes |
| `augmentation_pipeline` | No | Yes | No | No | No | No |
| `speech_enhancer` | Optional | Yes (CPU) | No | Yes | No | Yes |
| `speaker_separator` | Optional | No | No | Yes | No | No |
| `environment_simulator` | No | No | No | No | No | No |
| `feature_frontend` | No | Yes | No | Yes | Yes | Yes |
| `stream_processor` | No | Yes | Yes | Yes | Yes | No |
| `audio_event_detector` | Optional | Yes (TFLite) | Yes | Yes | Yes | No |
| `audio_classifier` | Optional | Yes (TFLite) | No | Yes | Yes | No |
| `speech_synthesizer` | Optional | No | No | Yes | No | No |
| `voice_converter` | Optional | No | No | Yes | No | No |
| `audio_generator` | Yes | No | No | No | No | No |
| `dataset_builder` | No | No | No | No | Yes | Yes |
| `trainer` | Optional | No | No | No | No | No |
| `evaluator` | No | No | No | No | Yes | No |
| `edge_optimizer` | No | No | No | No | Yes | Yes |
| `realtime_inference` | Optional | Yes (TFLite) | Yes | Yes | Yes | No |
| `dataset_balancer` | No | No | No | No | No | No |
| `dataset_versioner` | No | No | No | No | Yes | Yes |
| `experiment_tracker` | No | No | No | No | Yes | Yes |
| `deployment_packager` | No | No | No | No | Yes | Yes |
| `embedding_generator` | Optional | No | No | No | Yes | Yes |
| `multimodal_fusion` | Optional | No | No | Yes | No | No |

## Installing Nodes

```python
from app.core.plugins.manager import PluginManager

manager = PluginManager()
manager.install("PluginPackage/Audio/audio_conditioner/", upgrade=True)
manager.install("PluginPackage/Audio/segmenter/", upgrade=True)
manager.load_enabled_plugins()
# nodes are now available in the registry
```

```bash
graphyn plugin install PluginPackage/Audio/audio_conditioner/
graphyn plugin install PluginPackage/Common/dataset_builder/
```
