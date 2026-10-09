# F20 → other workers: requests (F-09 templates)

Written by the F20 worker (templates / marketplace / restored packs), updated 2026-10-08 evening (IST) after the
final live sweep on the image rebuilt at 17:26 IST. These are needs in paths F20 does not own. Nothing here is
committed by F20. Status per item: **OPEN**, **PARTLY DONE** or **DONE (F19.x)**.

## For F19 (app/, docker, images, container restarts)

1. **Image copies of docs/examples go stale after every F20 commit** — PARTLY DONE. The 17:26 rebuild shipped the
   175-entry catalog and the real `examples/31_video_demo/data/clip.mp4`. F20.13–F20.16 changed
   `docs/PIPELINE_TEMPLATE_CATALOG.json`, `docs/PIPELINE_TEMPLATE_VERIFICATION.json`, seed graphs and example 06 after
   that build, so `/app/docs` and `/app/examples` (live `POST /pipelines/marketplace/materialize`, example templates)
   lag until the next rebuild. Please rebuild (or bind-mount `docs/` + `examples/` read-only) once F20 is done.
   The `wakeword_export_onnx` fix (F20.13) is live only because F20 copied `nodes.py` into the bind-mounted
   `/app/plugins/wakeword-export-onnx/`; the image's `PluginPackage/WakeWord` copy is older.
2. **Restored plugins after restart / bundled allowlist** — OPEN. `GRAPHYN_BUNDLED_PLUGIN_ALLOWLIST` lists only the
   kept plugins. The 40 restored F20 plugins load from `/app/plugins` (repo `plugins/`, bind mount, installed via
   `POST /api/v1/plugins/install`). A fresh volume/host loses them: add the restored slugs (Agents, Audio/Common
   restored, Video, WakeWord) to the allowlist or keep the install step in the deploy docs.
3. **Isolated-venv torch policy + startup reconciliation** — OPEN.
   - `plugins/install upgrade=true` and the startup bundled-plugin reconciliation re-create venvs from PyPI and pull
     CUDA `torch 2.14.1` + 15 `nvidia-*` wheels (~4.5 GB per venv) next to CPU `torchaudio` (ABI mismatch:
     `libtorchaudio` fails to load). This filled the root disk on 2026-10-08. F20 repaired speech-enhancer,
     wakeword-data-gen, wakeword-export-onnx, wakeword-feature-extract and wakeword-train to `torch 2.12.1+cpu` /
     `torchaudio 2.11.0+cpu` from `/data/graphyn-home/f20_wheelhouse`.
   - Please install with a CPU index (`PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu`, or the wheelhouse)
     and pin torch/torchaudio as a pair.
   - During reconciliation `/nodes` reports a partial registry (e.g. 40 of 76 types) and runs are refused with
     422 "Unknown node type"; consider a readiness flag (`/health` not ready until the registry is complete).
4. **`app/core/plugins/isolated_schema.py` `_eval_field_default`** — OPEN. `Field(default_factory=lambda: [..])` is
   read as `[]` on the host, so the isolated worker gets an empty list and fails `min_length=1`. F20 switched
   `wakeword_data_gen` to literal defaults (F20.9). Kept plugins with the same pattern: `http_request.retry_on_status`,
   `guardrail_filter.policies`, `video_ingest.extensions`.
5. **Isolated boundary refuses `numpy.memmap`** (`isolated_executor._DENIED_NUMPY_NAMES`) — OPEN. F20 fixed
   `speech_enhancer`; converting memmap → ndarray during serialisation would avoid the class of failure.
6. **Pydantic models crossing the isolated boundary arrive as dicts** in in-process nodes — OPEN (F20 handles it in
   `multimodal_fusion`). A shared helper in `app.core.nodes.payload` would avoid per-node handling.
7. **Egress allowlist** — PARTLY DONE. Ollama now works (agents local-llm-chat / agent-loop / guarded-reply,
   video frame-captions-local-vlm all succeeded live). Still blocked: `api.github.com` (example 27 live variant,
   run 34eac9ba) and `httpbin.org`. Hosts the restored plugins fetch from: `huggingface.co`,
   `objects.githubusercontent.com`, `github.com` (Piper / kNN-VC release assets), `tfhub.dev`, `download.pytorch.org`.
8. **Image packages / MCP auth** — PARTLY DONE. F19.30 is live: `mcp_tool_call` no longer needs the `mcp` SDK
   (live run 62d6471d now fails clearly with needs-credentials: set `config.connection_id` to a `graphyn_mcp`
   credential / agent token). The marketplace template `tpl-agents-tool-router-mcp` is therefore
   `needs-credentials`, not a missing package. `espeak-ng` is still missing (Piper TTS phonemizer for
   `speech_synthesizer` piper backend and the WakeWord Piper path; the MMS-TTS fallback works without it,
   which is what the live wake-word runs used).
9. **Kept Agents plugins still carry `stub` flags** in config (`guardrail_filter`, `hitl_approve`, `llm_chat`,
   `output_schema_validate`, `prompt_template`); `guardrail_filter.Config` should validate policy names (a typo such
   as `secrets` passes validation and fails at run time; valid: jailbreak, pii, profanity, secret) — OPEN.
10. **Materializer (`app/core/templates/pipeline_template_materializer.py`)**: `mcp_tool_call` `stub` setdefault and
    branches for removed packs (`rag_fs_connector`, vision/yolo, mcu, ship packagers) — OPEN, safe to drop.
11. **`graphyn-ui/public/marketplace-catalog.json`** must be regenerated from `docs/PIPELINE_TEMPLATE_CATALOG.json`
    (175 entries, schema 2.0) — OPEN.
12. **Run-scoped path rewrite hits read-only inputs** (`app/core/paths/workspace_paths.py`, `_OUTPUT_KEYS` includes
    `model_path`) — NEW, OPEN. A `model_path` under `workspace/artifacts/<slug>/…` that a node only *reads* is rewritten
    to `workspace/artifacts/<slug>/runs/<run_id>/…`, so a template cannot point at a model a previous run exported
    (live run 6881de53, `wakeword_infer`). F20 moved the wake-word hand-off to `workspace/models/wakeword/<name>`
    (F20.16). Suggest scoping only keys a node declares as write paths, or skipping paths that already exist as files.
13. **Host CLI `validate` builds isolated venvs** — NEW, OPEN. `venv/bin/python -m app.cli.main validate --graph
    examples/06_speech_commands_e2e/pipeline_preprocess.graph.json` ran pip installs for unrelated plugin venvs
    (`pii-redact`, …) and was still running after 14 minutes (killed by F20). Validation should not create venvs.
14. **Dataset immutability vs. append flows** — FYI. `audio_exporter` refuses `append` to a version any run
    references, which broke example 06's six chained per-label shards on every re-run. F20.14 replaced them with one
    all-labels run. An `append` to the *newest* version with a clear error suggestion is fine as is; no change needed
    unless other append-chained graphs exist outside examples/.
15. `PluginPackage/Common/realtime_inference` is F19's; it is one of the shipped node types no marketplace base uses
    (with `credential_probe`, `http_webhook`, `set_map`, `webhook_trigger`).
