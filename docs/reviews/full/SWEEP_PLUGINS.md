# Plugin sweep — 36 live node types

Tip `6978329f529c59567fdfa4397c5bea5a6b1c9099` · branch `test/example-06-plugins` · generated 2026-10-08 (IST) · Mode A live API (`graphyn-api` :8001), project `review-full-2026-10-08`.

Run IDs below are 8-char prefixes of runs on the live stack (full IDs in `SWEEP_PLUGINS.csv` context / `GET /api/v1/runs?project=review-full-2026-10-08`).

## Headline

- Node types registered live: **36** (35 plugins; trainer+model_builder share one plugin). All 36 load live; all 36 have ≥1 successful live run in their default mode.
- Default-mode status: Working 36
- Sub-mode / cross-cutting rows: Stub 11, Needs-external 4, Broken 4
- **"Working" means the default path ran end-to-end live. It does NOT mean every mode works**: 11 modes are stubs/placeholders (incl. llm_chat default provider and structured_llm heuristic) (NOT IMPLEMENTED under the honesty rule) and 4 defects are Broken (see sub-mode table).
- Manifest gaps: 7 Audio plugins + deployment_packager have no `runtime` key in plugin.toml (default inprocess assumed).
- Port typing: Audio ports are `builtins.list` ("List of AudioSample" in prose only); Common/Agents workflow ports are `object` — no type checking at wire time for those.

## Per node (default mode)

| Pack | Node type | Status | Runtime | In/Out | Cred kinds | ArtifactRef | Unit test files | Live evidence | Notes |
|---|---|---|---|---|---|---|---|---|---|
| Agents | `guardrail_filter` | Working | inprocess | 1/2 | - | no | 1 | 21ce2372 (redact); 74273752 (block -> run failed = correct) |  |
| Agents | `hitl_approve` | Working | inprocess | 1/2 | - | no | 2 | b680559a (unattended policy); a111938f, bd929e4f (paused at awaiting_approval, approved via API, resumed) |  |
| Agents | `llm_chat` | Working | inprocess | 2/1 | openai_compat|anthropic|gemini|ollama | no | 3 | 00f15024, ebec6264 (ollama tinyllama real completion "Capitale: Paris"); c366d9d7, b8bc73a5 (provider=local) | DEFAULT provider "local" is an extractive echo, not an LLM (Agents/llm_chat/nodes.py:147-151,191-195) - must be labelled. openai_compat/anthropic/gemini = Needs-external (not called). |
| Agents | `output_schema_validate` | Working | inprocess | 1/2 | - | no | 1 | de8ac9ec (plain); 2d793dd8 | Interop defect with CodeResult (validates the wrapper). |
| Agents | `prompt_template` | Working | inprocess | 2/1 | - | no | 1 | 0d5bf721 (plain ok); fbee33c8 (fails on CodeResult) | Interop defect. |
| Audio | `audio_conditioner` | Working | MISSING | 1/1 | - | no | 31 | 6b4e8412 (1200 clips -> 2518 wavs); ex01 3e8f2410; ex02 cca7f7a7 |  |
| Audio | `audio_exporter` | Working | MISSING | 1/1 | - | no | 16 | 6b4e8412 (1200 clips -> 2518 wavs); ex01 3e8f2410; ex02 cca7f7a7 |  |
| Audio | `audio_quality_gate` | Working | MISSING | 1/2 | - | no | 9 | 6b4e8412 (1200 clips -> 2518 wavs); ex01 3e8f2410; ex02 cca7f7a7 |  |
| Audio | `augmentation_pipeline` | Working | MISSING | 1/1 | - | no | 9 | 6b4e8412 (1200 clips -> 2518 wavs); ex01 3e8f2410; ex02 cca7f7a7 |  |
| Audio | `dataset_ingest` | Working | MISSING | 0/1 | - | no | 23 | 6b4e8412 (1200 clips -> 2518 wavs); ex01 3e8f2410; ex02 cca7f7a7 |  |
| Audio | `feature_frontend` | Working | MISSING | 1/1 | - | no | 15 | 28dadbee (training chain); 78c0a2a5 |  |
| Audio | `segmenter` | Working | MISSING | 1/1 | - | no | 18 | 6b4e8412; ex01 3e8f2410 | mode=speaker_turn is a PLACEHOLDER that falls back to silence segmentation (Audio/segmenter/nodes.py:427-435) -> NOT IMPLEMENTED for that mode. |
| Common | `credential_probe` | Working | inprocess | 1/1 | openai_compat|ollama|smtp | no | 0 | b18f2e63 (ollama); ace27679 (smtp, redacted) | No unit test file references credential_probe (0). |
| Common | `csv_table` | Working | inprocess | 1/1 | - | yes | 4 | 2c8ea757 (write+read); 60772587, c4889916 (read existing artifact ok); 131a8e08, 8da9c3d9 (read bundled dataset CSV FAILS) | Cannot read CSVs under datasets/input/* that are symlinks into examples/ ("outside the workspace" / doubled workspace/workspace path). |
| Common | `dataset_builder` | Working | isolated | 1/1 | - | no | 19 | 28dadbee (2 epochs, test_accuracy 0.154); ex06 train chained 10b707ec | dataset_builder output is DatasetArtifact, does not emit ArtifactRef. |
| Common | `deployment_packager` | Working | MISSING | 1/1 | - | yes | 6 | 28dadbee (edge); 50daf859 (mcu header ok; cmsis_pack/arduino/zephyr/pte_bundle -> PACKAGE_STUB.txt) | Targets cmsis_pack/arduino/zephyr/pte_bundle are STUBS (Common/deployment_packager/nodes.py:940, 975-976, 1375-1382); description does not say so. No runtime key in plugin.toml. |
| Common | `edge_optimizer` | Working | isolated | 1/1 | - | yes | 17 | 28dadbee (tflite int8); 50daf859 (tflite float32 ok; tflm/executorch/ultralytics_export -> BACKEND_STUB.txt, run "succeeded") | Backends tflm/executorch/ultralytics_export are STUBS (Common/edge_optimizer/nodes.py:256, 799-849); recommends tflm_quantize/executorch_export/yolo_export nodes that do not exist on this branch. |
| Common | `error_catch` | Working | inprocess | 2/2 | - | no | 2 | d6630a0e (IR 1.3 on_error route ok); 8ae440a9; 386a3819/a567da3b fail without route | Only works with IR 1.3 node-level on_error {mode:route} + edge from error port; placing it downstream alone does not catch. |
| Common | `eval_gate` | Working | inprocess | 1/2 | - | no | 2 | 7fc4d2aa (pass); 65633f56 (threshold fail = correct) | Unwraps CodeResult correctly. |
| Common | `evaluator` | Working | isolated | 2/1 | - | yes | 21 | 28dadbee (2 epochs, test_accuracy 0.154); ex06 train chained 10b707ec |  |
| Common | `http_request` | Working | inprocess | 1/1 | - | no | 5 | 883b54d9 (loopback 127.0.0.1:8001 reached); 68c0b677 (public); 3670584c (169.254.169.254 attempted, timed out - NOT blocked) | No SSRF block in default egress mode "trusted" (app/core/config.py:609). |
| Common | `http_webhook` | Working | inprocess | 1/1 | - | no | 3 | 31b7fd35 (POST dispatched, non-2xx 405 surfaced as failure) | Success path to a 2xx sink not exercised (no external posts allowed). Uses validate_http_egress_url (http_webhook/nodes.py:137) - same trusted default. |
| Common | `if_switch` | Working | inprocess | 1/4 | - | no | 3 | 85b34ff3 (plain ok); 0365bb5a, 2c1163a5 (fail on CodeResult / UI-style expr) | Expression must reference output[...]; UI description implies bare field names. |
| Common | `json_transform` | Working | inprocess | 1/1 | - | no | 2 | cdc47948 (plain ok); a5d2b9bd (wrapper not unwrapped) | Interop defect with python_code output. |
| Common | `merge` | Working | inprocess | 2/1 | - | no | 15 | 3a0fbead (append); 37a7f2ef (combine_by_key ok); bbdec719 | append of two dicts is a shallow {**a,**b} (b wins on key collision, Common/merge/nodes.py:92-93) - surprising for a mode named "append". |
| Common | `object_store` | Working | inprocess | 1/1 | - | yes | 2 | 5ff22117 (put dict{path} ok, 19 B written); c2abc460, b8a6bf98, c3e3c178 (put returns [] silently) | local put is a SILENT NO-OP for dict-without-path, CodeResult and CsvTableResult (.path attr) inputs (Common/object_store/nodes.py:82-106, 262-270). S3 backend untested (Needs-external). |
| Common | `python_code` | Working | inprocess | 1/1 | - | no | 15 | 2f0f9c7d (ok); 6330fa55 (import os blocked = correct) | Output wrapped as CodeResult{data,metadata}; most downstream Common/Agents nodes do NOT unwrap it (see set_map 168c5f5d, if_switch 2c1163a5, prompt_template fbee33c8). Sandbox builtins lack ValueError etc (386a3819: "name ValueError is not defined"). AST filter, not a sandbox (documented). |
| Common | `realtime_inference` | Working | isolated | 1/1 | - | no | 10 | 78c0a2a5 (tflite) | backend=ultralytics/auto with audio input raises NotImplementedError (Common/realtime_inference/nodes.py:446). |
| Common | `schedule_trigger` | Working | inprocess | 0/1 | - | no | 2 | f3bb744a | Node emits a tick payload only; actual firing is via /system schedules (not exercised by this review). |
| Common | `send_email` | Working | inprocess | 1/1 | smtp | no | 3 | 827245bd (config dry_run); 8f561bc9 (SMTP_DRY_RUN env forces dry-run) | Real SMTP send = Needs-external (deliberately not attempted). |
| Common | `set_map` | Working | inprocess | 1/1 | - | no | 8 | 111545b0 (plain dict ok); 168c5f5d (operates on CodeResult wrapper) | Interop defect with python_code output. |
| Common | `structured_llm` | Working | inprocess | 1/1 | openai_compat|ollama | no | 6 | 69a01260 (ollama ran); 20a5ba9f, b1b535db (local_heuristic) | local_heuristic copies whole input text into each string field (fake-ish extraction). Paid providers Needs-external. |
| Common | `trainer` | Working | isolated | 2/1 | - | yes | 40 | 28dadbee (2 epochs, test_accuracy 0.154); ex06 train chained 10b707ec |  |
| Common | `model_builder` | Working | isolated | 1/1 | - | yes | 40 | 28dadbee (2 epochs, test_accuracy 0.154); ex06 train chained 10b707ec |  |
| Common | `wait_delay` | Working | inprocess | 1/2 | - | no | 3 | 598879f7 |  |
| Common | `webhook_trigger` | Working | inprocess | 3/3 | - | no | 3 | a8cce756; 5ff22117 | Emits sample_body in manual runs; inbound hook delivery (hooks API) not exercised. |

## Sub-modes, stubs and cross-cutting defects

| Node | Mode | Status | Evidence | Detail |
|---|---|---|---|---|
| `edge_optimizer` | backend=tflm | **Stub** | 50daf859 | writes BACKEND_STUB.txt; run reports success (nodes.py:799-849) |
| `edge_optimizer` | backend=executorch | **Stub** | 50daf859 | writes BACKEND_STUB.txt (nodes.py:799-849) |
| `edge_optimizer` | backend=ultralytics_export | **Stub** | 50daf859 | writes BACKEND_STUB.txt (nodes.py:799-849) |
| `deployment_packager` | target=cmsis_pack | **Stub** | 50daf859 | PACKAGE_STUB.txt (nodes.py:1375-1382) |
| `deployment_packager` | target=arduino | **Stub** | static | PACKAGE_STUB.txt (nodes.py:1375-1382) |
| `deployment_packager` | target=zephyr | **Stub** | static | PACKAGE_STUB.txt (nodes.py:1375-1382) |
| `deployment_packager` | target=pte_bundle | **Stub** | static | PACKAGE_STUB.txt (nodes.py:940,975-976) |
| `segmenter` | mode=speaker_turn | **Stub** | static | placeholder -> silence fallback (nodes.py:427-435) |
| `realtime_inference` | backend=ultralytics|auto + audio | **Stub** | static | raise NotImplementedError (nodes.py:446) |
| `llm_chat` | provider=local (default) | **Stub** | c366d9d7 | extractive echo, not a model (nodes.py:147-151) |
| `llm_chat` | provider=openai_compat|anthropic|gemini | **Needs-external** | - | paid APIs not called |
| `structured_llm` | provider=openai_compat | **Needs-external** | - | paid API not called |
| `structured_llm` | provider=local_heuristic | **Stub** | 20a5ba9f | copies full text into fields |
| `send_email` | real SMTP send | **Needs-external** | - | dry-run only (by constraint) |
| `object_store` | backend=s3 | **Needs-external** | - | no S3 creds/endpoint used |
| `object_store` | put of non-path inputs | **Broken** | c2abc460,b8a6bf98,c3e3c178 | silent [] no-op |
| `csv_table` | read datasets/input symlinked CSV | **Broken** | 131a8e08,8da9c3d9 | path resolution rejects symlinked inputs |
| `http_request` | SSRF block (default) | **Broken** | 883b54d9,3670584c | loopback + metadata not blocked in trusted mode |
| `*Common/Agents*` | consume python_code CodeResult | **Broken** | 168c5f5d,a5d2b9bd,2c1163a5,fbee33c8 | wrapper not unwrapped by set_map/json_transform/merge/if_switch/prompt_template/output_schema_validate/llm_chat/structured_llm/object_store |

## Not covered / limits

- Mode B (distributed) execution of any node: NOT run — live Mode B stack is down and `transfer.py` materialization is broken (see SUMMARY F-01).
- Isolated-runtime plugins ran in their isolated venvs under Mode A only.
- Removed packs (RAG, Vision, Video, TinyML, WakeWord, MLOps, and Audio annotator/classifier/ASR etc.) are not registered on this branch; any template using them is Invalid (see SWEEP_TEMPLATES).
