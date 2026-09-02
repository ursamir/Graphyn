# Graphyn local E2E report

- **Branch:** `cursor/usecase-plugins-workflows` @ `afde118` plus local fix commit
- **When:** 2026-09-02 ~14:50–15:00 IST (UTC+5:30)
- **Env:** `.venv-test`, `GRAPHYN_HOME=/workspace/Graphyn/.graphyn-e2e`, `GRAPHYN_SKIP_PLUGIN_LOAD=0`
- **Plugins installed via CLI:** dataset_ingest, audio_conditioner, asr_transcribe, pii_redact, structured_llm, eval_gate, http_webhook, caption_export, doc_parse_chunk, object_store, http_request, if_switch, set_map, json_transform, schedule_trigger, python_code, error_catch, merge, wait_delay, csv_table
- **Audio:** synthetic WAVs via `examples/generate_test_audio.py` copied to `examples/01_wake_word/data/wake_word/` (8 files). Did not download Speech Commands archives.
- **HTTP:** local BaseHTTPRequestHandler on `127.0.0.1:45811` was started; graphs were switched to `provider=mock` so E2E does not depend on example.com.

## Pipelines 22–28

| Pipeline | Result | Run id (prefix) | Duration | Notes |
|---|---|---|---|---|
| 22_call_analytics | **PASS** | `5058e130f553` | 15.6s | ingest+conditioner dominate runtime |
| 23_meeting_crm | **PASS** | `71e02e15f500` | 1.7s | |
| 24_captions | **PASS** | `0cf68586248b` | 0.01s | wrote `examples/24_captions/output/captions.{srt,vtt,json}` |
| 25_doc_rag_ingest | **PASS** | `068716d3fbff` | 0.01s | wrote `examples/25_doc_rag_ingest/output/store/chunks/` |
| 26_nightly_compliance | **PASS** | `fb6b1cb10259` | 0.02s | wrote `examples/26_nightly_compliance/output/compliance.csv` |
| 27_github_triage | **PASS** | `657f333155a1` | 1.5s | mock HTTP + mock ASR |
| 28_asr_eval_merge | **PASS** | `2d5c84137c1a` | 0.01s | wrote `examples/28_asr_eval_merge/output/merged.csv` |

Command: `python -m app.cli.main run --graph examples/<n>/pipeline.graph.json`

## MCP agentic loop

In-process handlers (no stdio hang): `install_plugin`, `list_plugins`, `list_nodes`, `generate_graph` (http_request + if_switch with edge `condition`, plus `schedule_trigger` event_trigger), `validate_graph`, `execute_pipeline`, poll `inspect_run`.

| Step | Result |
|---|---|
| install_plugin | **PASS** (already installed) |
| list_plugins | **PASS** (20 plugins) |
| list_nodes | **PASS** (20 types) |
| generate_graph + condition | **PASS** |
| generate_graph event_trigger | **PASS** (`source_type=timer`) |
| validate_graph | **PASS** |
| execute_pipeline | **PASS** (`f5f5dfdd357e…`, status started) |
| inspect_run | **PASS** (status completed) |

**MCP loop: PASS**

## Failures found and fixes applied

1. **`http_webhook` hung / called example.com** — added `provider` + `mock_response` (timeout capped at 30s). Graphs 22/23 and matching templates use `provider=mock`, `timeout_s=2`.
2. **Examples 26/27 pii edge used `src_port: output`** — pii_redact only exposes `transcript` / `audio` / `audit`. Edges now use `transcript`.
3. **Example 28 `python_code` source had literal `\\n` instead of newlines** — syntax-valid source with real newlines.
4. **Port compat: `list[AudioSample]` ↛ `object \| None`** — `CompatibilityChecker` treated PEP 604 unions (`types.UnionType`) as non-unions and required a non-generic source for Union inputs. Now `list[T]` may flow into `object | None`.
5. **`generate_graph` / IRNode `cannot pickle mappingproxy`** — nested frozen configs broke `copy.deepcopy`. Added `_deep_unfreeze` before freeze/deepcopy; MCP rebuild uses it.

## Unit tests

`GRAPHYN_SKIP_PLUGIN_LOAD=1 pytest` on related suites: **156 passed** (`test_compat`, MCP graph/execution/plugins, common plugins http_webhook/pii/http_request/if_switch/python_code/eval_gate/asr_transcribe, `unit_test/core/ir`). Installed `hypothesis` in `.venv-test` for collection.

## Skips

| Item | Why |
|---|---|
| examples/01_wake_word | Needs `segmenter` (and further Audio plugins) not in the 22–28 plugin set. Data exists; run failed on unregistered `segmenter`. |
| examples/06_speech_commands_e2e | Trainer / TF / GPU-adjacent (`pipeline_train_ml.graph.json`). Skipped as instructed. |
| `prepare_real_data.py` | Would download Speech Commands archives. Used synthetic WAVs instead. |
| Heavy ML / torch / isolated trainer plugins | Not required for 22–28 mock E2E. |

## Remaining risks

- Shared `~/.graphyn/plugins/registry.json` still has stale pytest tmp install paths; E2E used isolated `GRAPHYN_HOME=.graphyn-e2e`.
- `cli validate` previously failed on mappingproxy for some plugin configs; should be fixed by IR unfreeze but was not re-run after that fix.
- Plugin `--upgrade` in the same CLI process can log DuplicatePortTypeError; a fresh process loads cleanly.
