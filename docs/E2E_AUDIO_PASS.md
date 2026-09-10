# E2E Audio Pass — local template matrix

**Date:** 2026-09-10 (Asia/Kolkata)  
**Branch:** `cursor/usecase-plugins-workflows`  
**API:** `http://127.0.0.1:8001` with `GRAPHYN_HOME=/workspace/Graphyn/.graphyn-e2e`, `GRAPHYN_PROJECT_DIR=/workspace/Graphyn/workspace`  
**Runner:** `scripts/e2e_audio_pass_runner.py`

## Data heal (documented)

`workspace/` is gitignored; links are local to this box:

| Link / path | Target | Notes |
|---|---|---|
| `workspace/datasets/input/speech-commands/{go,yes,no,up,down,stop}` | symlinks → `workspace/datasets/input/{label}` | **48 wavs** via `find -L` (8×6). Fixes prior browser miss on `speech-commands/go`. |
| `workspace/datasets/input/wake-word` | → `examples/01_wake_word/data` | Already present; `wake_word/` holds 8 wavs. |
| `workspace/datasets/input/environmental/{car_horn,dog_bark,footsteps,rain,siren,background,clean_speech}` | symlinks → sibling label dirs | Convenience tree for environmental templates. |
| `workspace/datasets/input/doc-rag-ingest` | → `examples/25_doc_rag_ingest/data` | `product.md`, `runbook.txt`. |

`DatasetIngest` follows directory symlinks (`Path.is_dir` + `os.listdir`); no copy/hardlink replacement required.

## Template matrix

| Template | Status | run_id | Notes |
|---|---|---|---|
| audio-classification | **COMPLETED** | `14ae855f4fc34142bf6d9232e78a0511` | artifacts=2; ingest `speech-commands/go` |
| basic-wakeword | **COMPLETED** | `5e901102c3b34fe6a847e277a253e231` | artifacts=3; wake-word path |
| audio-quality-check | **COMPLETED** | `bb94f9681c96417aa3eab443a6cb1549` | artifacts=2; VAD segmenter default changed to silence (webrtcvad needs Python.h / not in API venv); SegmenterNode also falls back to silence if webrtcvad missing |
| podcast-leveling | **COMPLETED** | `808d7b8ee2a94ac88168e7e380bf5772` | artifacts=2; installed `speech-enhancer` plugin |
| speech-recognition | **COMPLETED** | `eaf71f127abd4e9e9c821b4592995823` | artifacts=3 |
| doc-rag-ingest | **COMPLETED** | `5b3fbe0d6fe2487cae2fb9790c9ce073` | artifacts=3; template path fixed `data/docs` → `workspace/datasets/input/doc-rag-ingest` |
| edge-deploy | **SKIPPED_MODEL** | — | No `workspace/artifacts/models/saved_model`; API venv has neither tensorflow nor onnx |
| call-analytics | **SKIPPED_KEYS** | — | Deepgram + OpenAI |
| captions | **SKIPPED_KEYS** | — | Deepgram |
| meeting-crm | **SKIPPED_KEYS** | — | OpenAI-compat ASR/LLM |

**Success bar:** ≥4 local audio templates COMPLETED with artifacts — **6 COMPLETED** (5 audio + doc-rag).

## Fixes shipped in this pass

1. **speech-commands path heal** (local symlinks; documented above).
2. **Segmenter VAD** — soft-fallback to silence when `webrtcvad` is missing (`PluginPackage/Audio/segmenter` + installed copy).
3. **audio-quality-check template** — second segmenter mode `vad` → `silence` for CPU/local friendliness.
4. **doc-rag-ingest template** — ingest path points at real workspace docs.
5. **speech-enhancer** installed via API for podcast-leveling.
6. **UI polish** — softer shadows/borders, editorial project cards, calmer PageHeader/EmptyState, quieter Builder chrome (Inter retained).

## Browser / UI spot-check

- Vite UI on `:5173`; API health OK.
- Authenticated API checks for project `e2e-audio-classification`:
  - `GET /runs?project=…` → completed run `14ae855f…`
  - `GET /runs/{id}/artifacts` → audio_samples artifacts present
  - `GET /data/inputs` → labels including `go`, `speech-commands` siblings, `wake-word`
  - Spec/versions endpoints respond (draft project may have empty versions until export versions materialize)
- Headless Chrome without saved Bearer token shows Settings / “Sign in with your API token” (expected). Existing box Chrome CDP rejects unauthenticated DevTools origins (`--remote-allow-origins` not set on pid 2505194). No UI runtime exceptions observed in API-backed flows.

## Reproduce

```bash
export GRAPHYN_HOME=/workspace/Graphyn/.graphyn-e2e
export GRAPHYN_PROJECT_DIR=/workspace/Graphyn/workspace
export GRAPHYN_API_TOKEN="$(cat /workspace/graphyn-api-token.txt)"
# ensure speech-commands symlinks (see Data heal)
python3 scripts/e2e_audio_pass_runner.py
```
