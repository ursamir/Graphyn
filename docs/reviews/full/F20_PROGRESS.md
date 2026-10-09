F20 DONE

# F20 progress (F-09 templates)

Live runs finished 2026-10-08 19:27 IST. Safe for F19 rebuild (DIST-ORPHAN-1).

## Commits
- `e195355 F20.17: live verification JSON + catalog verified_run`
- `46df6b1 F20.16: wake-word chain hands the model over at a stable path — the wakeword templates write workspace/models/wakeword/<name> (config paths under workspace/artifacts are run-scoped, so a model_path there was rewritten to runs/<id>/, live run 6881de53) and wakeword-detect reads the exported .onnx file (model_path must be a file)`
- `0830cb9 F20.14: example 06 Phase 1 is one all-labels run (recursive ingest) instead of six append=true shards — appending to a dataset version that runs reference is refused (immutable versions), so the shards failed on every re-run (live runs 6589c565 … be2a7d5f); run_preprocess.sh, run_train.py and README follow, README dataset paths corrected to workspace/datasets/output/audio_export/latest`
- `d162e72 F20.15: wakeword-detect template reads the model where wakeword train/export write it (workspace/artifacts/wakeword/<name>, was workspace/models/wakeword — live run 79beb078 failed FileNotFoundError)`
- `67c615c F20.13: wakeword_export_onnx exports with its own legacy torch.onnx path (livekit-wakeword 0.2.3 renamed export_classifier -> export_onnx; live run 82a746c0 failed AttributeError), csv-transform template reads CsvTableResult.rows (live run b6fffdab failed 'tuple' object has no attribute 'get')`
- `75793bd F20.12: templates use structured_llm provider rule_based (the rebuilt image renamed local_heuristic; no deprecation warning on every run)`
- `3fab38f F20.11: examples 22-28 run offline out of the box (local Whisper + rule-based extract + local object store / CSV; live variants keep hosted providers with empty webhook URLs that fail clearly), READMEs describe offline vs live and real output paths, top-level call-analytics/meeting-crm templates no longer post to httpbin, example 19 streams an existing clip`
- `666762b F20.10: marketplace catalog rebuilt from 50 explicit base pipelines of shipped packs (175 entries, all validate; generator refuses invalid entries, statuses ready/needs-credentials/needs-endpoint/needs-upstream), one seed graph per base (35 stale seeds removed), platform node catalog regenerated from the shipped registry, marketplace/MCP docs and smoke defaults updated`
- `36c6ba5 F20.9: live isolated-runtime fixes — speech_enhancer returns plain arrays (denoiser memmap was refused at the isolated boundary), multimodal_fusion reads dict embeddings from isolated plugins, wakeword_data_gen literal list defaults (host stub read lambda factories as empty lists)`
- `52d5fda F20.8: live-run fixes for restored plugins — audio_classifier SISO process (live runs got dict keys), setuptools<81 for tensorflow_hub venvs, memory_store record key, output folders under Advanced, jargon-free descriptions`
- `86294c8 F20.7: drop RAG cases from core tests (pack stays out); registry test covers restored Video/Agents/WakeWord with a no-stub check (RAG/MLOps/Vision test files removed in 2337827)`
- `b17ca29 F20.6: WakeWord pack — 5 real nodes on livekit-wakeword (Piper/MMS data gen, augmentation + ONNX features, 3-phase training, ONNX/INT8 export, detection) + tests; pcm decoder test trimmed to surviving copy`
- `5a770e7 F20.5: restored Agents nodes adopt the F-06 payload contract (unwrap python_code/csv_table/http wrappers)`
- `78b084f F20.4: Video pack — 10 real nodes (ffmpeg/PySceneDetect/CLIP/VideoMAE/LLaVA captions), video tests, 31_video_demo data prep (Big Buck Bunny trailer)`
- `df3d31f F20.3: restore Audio plugins (alignment_node, audio_annotator, audio_classifier, audio_event_detector, audio_generator, environment_simulator, speaker_separator, speech_enhancer, speech_synthesizer, stream_ingest, stream_processor, voice_converter) with real implementations + tests`
- `14f5488 F20.2: restore Common plugins (asr_transcribe, caption_export, dataset_balancer, dataset_versioner, doc_parse_chunk, embedding_generator, experiment_tracker, multimodal_fusion, pii_redact) with real implementations + tests`
- `a853f3b F20.1: restore Agents pack (agent_loop LLM loop, mcp_tool_call auth, memory_store, tool_router)`

## File-template sweep
- `108` graphs in `sweep_f20_final.json`: **101 succeeded**
- Live validate: **139/139** (before: 129 files / 58 valid)
- Registry: 76/76 node types
- Expected clear failures only: mcp needs-credentials; ex22/23.live empty webhook; ex24/26/28.live API keys; ex27.live api.github.com egress

## Catalog sample (≥3 per family)
- `18` materialized+run: {('agents', 'succeeded'): 3, ('audio', 'succeeded'): 3, ('common', 'succeeded'): 3, ('cross', 'succeeded'): 3, ('video', 'succeeded'): 3, ('wakeword', 'succeeded'): 3}
  - `tpl-agents-guardrail-approval-memory` succeeded `39486a3304f745d193023fd80bf1c6c8`
  - `tpl-agents-structured-extract-validate` succeeded `097ae34fd4de4f559dfcfab89979d043`
  - `tpl-agents-tool-router-memory` succeeded `e82c0706601449be80bd51d82ca34f35`
  - `tpl-audio-classify-yamnet` succeeded `9d0a001263e54d5bb02de709f23c8d7d`
  - `tpl-audio-dataset-balance-version` succeeded `0f722c607d7b4587a12c0fb263e9e3eb`
  - `tpl-audio-embeddings` succeeded `d66cbff835d843d9b63e99af850cbed7`
  - `tpl-common-asr-captions` succeeded `eb7aba70d6c0464fb91f52beaef57b1d`
  - `tpl-common-asr-pii-redact` succeeded `316d5547b2a547cbb389761eede0a374`
  - `tpl-common-branch-merge-error` succeeded `be0d668da2154589a5590317e3ec1939`
  - `tpl-cross-call-analytics` succeeded `2f1c8bd9628942b7981fa27862e47133`
  - `tpl-cross-meeting-notes-memory` succeeded `ff211b5e02964cda93f999c7cd596108`
  - `tpl-cross-tts-asr-roundtrip` succeeded `79b746c3694745f58cf7312662548c12`
  - `tpl-video-action-recognition` succeeded `081cc7d4c0074675aeed58fc4b2ead1c`
  - `tpl-video-scene-clips` succeeded `a3a881507fe34302a1f52ce8ea6e88a1`
  - `tpl-video-transcribe-captions` succeeded `0894e9b60c724df08a977762ecb64b0e`
  - `tpl-wakeword-data-gen` succeeded `671b43c02b764b46ab35cac150524b7e`
  - `tpl-wakeword-features` succeeded `f23ba0ecc9bc4eb19c19a2c2fb8ec65d`
  - `tpl-wakeword-train-export` succeeded `c34b5d5ef8bc4cbe8affcd620391e90a`

## Artifacts
- `docs/PIPELINE_TEMPLATE_VERIFICATION.json` (committed F20.17)
- `docs/reviews/full/SWEEP_TEMPLATES_F20.md` (not committed)
- `docs/reviews/full/F20_REQUESTS.md` (not committed)
- this file (not committed)
