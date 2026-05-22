---
inclusion: always
---

## Context7

Use the Context7 MCP power to fetch up-to-date library docs before implementing or designing with any dependency.

**Trigger on:** uncertain API signatures, new integrations, or any library usage below.

| Layer | Libraries |
|-------|-----------|
| Audio core | `librosa`, `soundfile`, `scipy`, `webrtcvad`, `pyloudnorm` |
| Audio enhancement | `noisereduce`, `deepfilternet`, `pyroomacoustics`, `audiomentations` |
| Speech/Speaker | `pyannote.audio`, `speechbrain`, `ctc-forced-aligner` |
| Embeddings | `transformers`, `openl3` |
| ML frameworks | `tensorflow`, `keras`, `torch`, `torchaudio`, `onnxruntime` |
| Dataset/Hub | `datasets`, `huggingface_hub` |
| Generative | `TTS` (Coqui), `audiocraft` |
| API | `fastapi`, `uvicorn`, `httpx` |
| Frontend | `ReactFlow`, `Zustand`, `wavesurfer.js`, `js-yaml` |

Activate Context7 → resolve library ID → fetch relevant docs → then implement.
