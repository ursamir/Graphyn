# E2E Audio Pass — local template matrix

> **Superseded for full coverage:** see [`docs/E2E_TEMPLATE_MATRIX.md`](E2E_TEMPLATE_MATRIX.md) (2026-09-11 10:01 IST) — all UI templates + ex-01…30 + example folders, including free-path captions/call-analytics/meeting-crm via `local_whisper` / `local_heuristic`.

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
| edge-deploy | **COMPLETED** | `f51a66e3d4454061b8f89acddc23edce` | artifacts=3; tiny SavedModel at `workspace/artifacts/models/saved_model` (gitignored) trained via `scripts/train_tny_edge_model.py` using trainer plugin venv TF 2.21 (API host venv still has no TF; edge-optimizer isolated venv does) |
| call-analytics | **SKIPPED_KEYS** | — | Deepgram + OpenAI |
| captions | **SKIPPED_KEYS** | — | Deepgram |
| meeting-crm | **SKIPPED_KEYS** | — | OpenAI-compat ASR/LLM |

**Success bar:** ≥4 local audio templates COMPLETED with artifacts — **7 COMPLETED** (5 audio + doc-rag + edge-deploy).

## Fixes shipped in this pass

1. **speech-commands path heal** (local symlinks; documented above).
2. **Segmenter VAD** — soft-fallback to silence when `webrtcvad` is missing (`PluginPackage/Audio/segmenter` + installed copy).
3. **audio-quality-check template** — second segmenter mode `vad` → `silence` for CPU/local friendliness.
4. **doc-rag-ingest template** — ingest path points at real workspace docs.
5. **speech-enhancer** installed via API for podcast-leveling.
6. **UI polish** — softer shadows/borders, editorial project cards, calmer PageHeader/EmptyState, quieter Builder chrome (Inter retained).
7. **edge-deploy model** — trained TNY speech-commands SavedModel into gitignored `workspace/artifacts/models/saved_model` (plugin trainer TF); E2E run completed TFLite float32 + edge package.

## Browser / UI spot-check

- Vite UI on `:5173`; API health OK.
- Authenticated API checks for project `e2e-audio-classification`:
  - `GET /runs?project=…` → completed run `14ae855f…`
  - `GET /runs/{id}/artifacts` → audio_samples artifacts present
  - `GET /data/inputs` → labels including `go`, `speech-commands` siblings, `wake-word`
  - Spec/versions endpoints respond (draft project may have empty versions until export versions materialize)
- Headless Chrome without saved Bearer token shows Settings / “Sign in with your API token” (expected). Existing box Chrome CDP rejects unauthenticated DevTools origins (`--remote-allow-origins` not set on pid 2505194). No UI runtime exceptions observed in API-backed flows.



## Browser E2E gap fixes (2026-09-10 IST)

| Gap | Fix |
|---|---|
| `speech-commands` showed 0 files | `GET /data/inputs` + `GET /data/inputs/{label}` now use `os.walk(..., followlinks=True)` so class-dir symlinks (`speech-commands/go/*.wav`) count and list. Unit test: symlink tree. Curl proof: `file_count=48`. |
| Project Versions empty after audio-classification | Root cause: segmenter `window_ms=3000` on ~0.6s clips → 0 segments → exporter early-return. Fixes: (1) template `window_ms=500`; (2) segmenter emits whole clip when shorter than window; (3) exporter always stamps `v1` + `labels.csv` + `lineage.json` (even empty); (4) NodeExecutor sets `node._run_id` so lineage includes `run_id`; (5) `list_versions` tolerates list-shaped `metadata.json`. Re-run `006c4274…` → `datasets/output/e2e-audio-classification/v1` with 32 samples + `run_id`. |
| Spec / Taxonomy / Contract blank | `ProjectManager.create` seeds `spec.md`, starter taxonomy, contract with hint; UI textareas get placeholders. |
| Artifact deep-link stale project | `openArtifacts` / `openTrace` / `openRun` accept `project`; RunsView + ArtifactsView sync `activeProject` from `run.meta.project`. |

## Reproduce

```bash
export GRAPHYN_HOME=/workspace/Graphyn/.graphyn-e2e
export GRAPHYN_PROJECT_DIR=/workspace/Graphyn/workspace
export GRAPHYN_API_TOKEN="$(cat /workspace/graphyn-api-token.txt)"
# ensure speech-commands symlinks (see Data heal)
# edge-deploy: train tiny SavedModel first (uses .graphyn-e2e/plugins/venvs/trainer TF)
.graphyn-e2e/plugins/venvs/trainer/bin/python scripts/train_tny_edge_model.py
python3 scripts/e2e_audio_pass_runner.py
```
