# E2E Template Matrix — full local pass

**Date:** 2026-09-11 10:01 IST  
**Branch:** `cursor/usecase-plugins-workflows`  
**API:** `http://127.0.0.1:8001` with `GRAPHYN_HOME=/workspace/Graphyn/.graphyn-e2e`, `GRAPHYN_PROJECT_DIR=/workspace/Graphyn/workspace`  
**Runners:** `scripts/e2e_all_templates_runner.py` (primary), `scripts/e2e_audio_pass_runner.py` (legacy audio subset)

## Free provider strategy

| Role | Provider | Notes |
|---|---|---|
| ASR | `local_whisper` / `faster_whisper` | `faster-whisper` tiny on CPU in API venv; returns Transcript + word timings |
| ASR alt | `openai_compat` + Groq | If `OPENAI_API_KEY` missing and `base_url` looks like groq.com, uses `GROQ_API_KEY` |
| LLM | `local_heuristic` | Deterministic schema fill for E2E (call-analytics / meeting-crm) |
| LLM alt | `openai_compat` + Groq | Same Groq key fallback as ASR |
| Webhooks | `https://httpbin.org/post` | Replaces example.com callbacks so runs do not hang |

Key-gated templates (`captions`, `call-analytics`, `meeting-crm` and ex-22/23/24) were updated in both `examples/templates/` and `workspace/configs/templates/` to the free path. Runner also stamps free providers at run time.

## Summary

| Bucket | COMPLETED | SKIPPED_* | N/A_* | FAILED |
|---|---:|---:|---:|---:|
| Templates (UI + ex-*) | **28** | 2 | 0 | **0** |
| Example folders 01–30 | **18** | 2 | 10 | **0** |

## Template matrix

| Template | Status | run_id | Notes |
| --- | --- | --- | --- |
| audio-classification | COMPLETED | f8a7dfccf608445b8e8a91470d89bc0f | artifacts=1; fresh reconfirm |
| basic-wakeword | COMPLETED | 15eeb3dae1f74bf7a46f57f66dd6dc3e | artifacts=1 |
| audio-quality-check | COMPLETED | 4556c917ba4c48ba877f9541b0959a49 | artifacts=1 |
| podcast-leveling | COMPLETED | a0c24ef1fce8433f8235134ea2aacbaf | artifacts=1 |
| speech-recognition | COMPLETED | d5bc6ec8e8034a99a4d3c01fc16f7f4c | artifacts=2 |
| doc-rag-ingest | COMPLETED | f9f33605a76e4fc19c89be767d6630c5 | artifacts=3 |
| edge-deploy | COMPLETED | dfa82f23af3d4ed9a7dcc6814dd9445f | artifacts=3 |
| captions | COMPLETED | ef5a52c687f64f24a9a7f3285ea94b5e | local_whisper ASR (free); artifacts=3 |
| call-analytics | COMPLETED | 6858e0deec4e42adae4c1ff04797e63a | local_whisper + local_heuristic + httpbin; artifacts=7 |
| meeting-crm | COMPLETED | b7882cd61bc64d599e0d950a59b5566e | local_whisper + local_heuristic + httpbin; artifacts=5 |
| ex-01-wake-word | COMPLETED | 08fee9781ef248eea553224b8f279d8a | artifacts=3 |
| ex-02-speech-commands | COMPLETED | dac9d278999d4bf0894deb72e8a74e0b | artifacts=4 |
| ex-03-environmental-sounds | COMPLETED | 8d6357685a094fe7945062c89b9df103 | path heal environmental-sounds/*; artifacts=4 |
| ex-04-speaker-verification | COMPLETED | 390042cd31ae484b85f682abb4b5554a | path heal speaker-verification/*; artifacts=4 |
| ex-05-speech-enhancement | COMPLETED | a677e544302f45c5a3761986e260c2e9 | path heal speech-enhancement/*; artifacts=3 |
| ex-06-speech-commands-e2e | COMPLETED | b78feabaabc4408c8b9b3613c71b4466 | followlinks ingest + exclude_none isolated dump; artifacts=6 |
| ex-09-parallel-execution | COMPLETED | 3a5f670ec30449f6a4cba20cebb9e8bb | artifacts=11 |
| ex-10-resumable-pipeline | COMPLETED | 6cde5d2375384063860553dc93b8fe78 | artifacts=1 |
| ex-12-conditional-branching | COMPLETED | 2a42356c0b3840fdb3423364e414ebd2 | stamp no longer injects project into artifact sinks; artifacts=7 |
| ex-18-pipeline-composition | COMPLETED | 56d58286cce243dba0c025b454bf1d16 | artifacts=3 |
| ex-19-capability-scheduling | COMPLETED | b9150da55b29494db634f419c1cf9fbe | file_path → yes_000.wav; artifacts=2 |
| ex-22-call-analytics | COMPLETED | 5b2219b4b78b43d9bef2e52edbabeb3b | free ASR/LLM path; artifacts=3 |
| ex-23-meeting-crm | COMPLETED | 9b2d0c50d47747f195e7e61f4c1cef0c | free ASR/LLM path; artifacts=3 |
| ex-24-captions | COMPLETED | 64d40a3378e24f9b9fab0a54e2fd8831 | local_whisper; artifacts=1 |
| ex-25-doc-rag-ingest | COMPLETED | c3b6567b744d4146a868ee3aee90eafe | artifacts=3 |
| ex-26-nightly-compliance | SKIPPED_EXTERNAL | — | Slack chat.postMessage — needs Slack token |
| ex-27-github-triage | SKIPPED_EXTERNAL | — | GitHub Issues API — needs GitHub token |
| ex-28-asr-eval-merge | COMPLETED | aa9e4a2f19124be6ab82d2d3408c0f33 | local_whisper ASR eval merge; artifacts=4 |
| ex-29-distributed-placement | COMPLETED | 8c776657314c4e3d983efaf79ec3acad | artifacts=3 |
| ex-30-edge-deploy | COMPLETED | 83d6712b231a44b28e69e9298b391fde | artifacts=3 |

## Example folder matrix

| Example | Status | run_id | Notes |
| --- | --- | --- | --- |
| 01_wake_word | COMPLETED | 08fee9781ef248eea553224b8f279d8a | via ex-01-wake-word |
| 02_speech_commands | COMPLETED | dac9d278999d4bf0894deb72e8a74e0b | via ex-02-speech-commands |
| 03_environmental_sounds | COMPLETED | 8d6357685a094fe7945062c89b9df103 | via ex-03 |
| 04_speaker_verification | COMPLETED | 390042cd31ae484b85f682abb4b5554a | via ex-04 |
| 05_speech_enhancement | COMPLETED | a677e544302f45c5a3761986e260c2e9 | via ex-05 |
| 06_speech_commands_e2e | COMPLETED | b78feabaabc4408c8b9b3613c71b4466 | via ex-06 |
| 07_mcp_agent_pipeline | N/A_SCRIPT | — | scripts=['agent.py']; README/CLI demo, not API template |
| 08_rest_api_streaming | N/A_SCRIPT | — | scripts=['stream_client.py']; streaming client demo |
| 09_parallel_execution | COMPLETED | 3a5f670ec30449f6a4cba20cebb9e8bb | via ex-09 |
| 10_resumable_pipeline | COMPLETED | 6cde5d2375384063860553dc93b8fe78 | via ex-10 |
| 11_artifact_lineage | N/A_SCRIPT | — | scripts=['lineage_demo.py'] |
| 12_conditional_branching | COMPLETED | 2a42356c0b3840fdb3423364e414ebd2 | via ex-12 |
| 13_csv_data_processing | N/A_SCRIPT | — | scripts=['csv_pipeline.py'] |
| 14_plugin_manifest | N/A_SCRIPT | — | scripts=['manifest_demo.py'] |
| 15_event_driven_pipeline | N/A_SCRIPT | — | scripts=['event_driven_demo.py'] |
| 16_deterministic_replay | N/A_SCRIPT | — | scripts=['replay_demo.py'] |
| 17_partial_execution | N/A_SCRIPT | — | scripts=['partial_demo.py'] |
| 18_pipeline_composition | COMPLETED | 56d58286cce243dba0c025b454bf1d16 | via ex-18 |
| 19_capability_scheduling | COMPLETED | b9150da55b29494db634f419c1cf9fbe | via ex-19 |
| 20_retry_fault_tolerance | N/A_SCRIPT | — | scripts=['retry_demo.py'] |
| 21_runtime_control_api | N/A_SCRIPT | — | scripts=['runtime_control_demo.py'] |
| 22_call_analytics | COMPLETED | 5b2219b4b78b43d9bef2e52edbabeb3b | via ex-22 free path |
| 23_meeting_crm | COMPLETED | 9b2d0c50d47747f195e7e61f4c1cef0c | via ex-23 free path |
| 24_captions | COMPLETED | 64d40a3378e24f9b9fab0a54e2fd8831 | via ex-24 local_whisper |
| 25_doc_rag_ingest | COMPLETED | c3b6567b744d4146a868ee3aee90eafe | via ex-25 |
| 26_nightly_compliance | SKIPPED_EXTERNAL | — | Slack token required |
| 27_github_triage | SKIPPED_EXTERNAL | — | GitHub token required |
| 28_asr_eval_merge | COMPLETED | aa9e4a2f19124be6ab82d2d3408c0f33 | via ex-28 |
| 29_distributed_placement | COMPLETED | 8c776657314c4e3d983efaf79ec3acad | via ex-29 |
| 30_edge_deploy | COMPLETED | 83d6712b231a44b28e69e9298b391fde | via ex-30 |

## Data / runtime heals

| Item | Fix |
|---|---|
| `speech-commands/{go,yes,…}` | Symlinks → label dirs (prior pass); 48 wavs |
| `environmental-sounds/*` | Symlinks → `dog_bark`, `car_horn`, … |
| `speaker-verification/*` | Symlinks → `speaker_001`… |
| `speech-enhancement/clean_speech` | Symlink → `clean_speech` |
| DatasetIngest `os.walk` | `followlinks=True` so class-dir symlinks ingest |
| `resolve_ingest_dir` / `_dir_has_ingest_files` | Symlink-aware walk (was treating speech-commands as empty) |
| Isolated trainer config | `model_dump(exclude_none=True)` so null schema pads do not override Field defaults |
| E2E stamp | Do not inject `project` into custom artifact sinks; strip null config keys; heal ML `output_path` |

## Reproduce

```bash
# one-time local data + workspace template free-path stamp
python3 scripts/heal_e2e_local_data.py

export GRAPHYN_HOME=/workspace/Graphyn/.graphyn-e2e
export GRAPHYN_PROJECT_DIR=/workspace/Graphyn/workspace
export GRAPHYN_API_TOKEN="$(cat /workspace/graphyn-api-token.txt)"
export GRAPHYN_API=http://127.0.0.1:8001
# faster-whisper already in graphyn-clean-venv
/workspace/graphyn-clean-venv/bin/python3 scripts/e2e_all_templates_runner.py
```

Machine-readable: `docs/_e2e_template_matrix.json`.
