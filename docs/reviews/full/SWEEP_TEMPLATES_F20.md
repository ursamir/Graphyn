# SWEEP_TEMPLATES_F20 — every advertised template, validated and run live

Generated 2026-10-08 19:27 IST by the F20 worker. API: graphyn-api :8001 (image rebuilt 2026-10-08 17:26 IST, includes F19 fixes and the restored F20 packs), project `review-f20-templates`, token `review-f20-templates` (id 6867e273d89d45d3).

## Counts before → after

| Measure | Before (review 2026-10-08) | After (F20) |
|---|---|---|
| File templates (examples/**/*.graph.json + workspace/configs/templates) | 129 files, 58 valid live | 139 files, 139 valid live |
| Marketplace catalog entries | 3032 (112 valid on the live stack) | 175 (50 base pipelines × industry presets), 175/175 validate (generator refuses invalid entries) |
| Catalog status mix | all `proposed`/`seeded` | {'needs-credentials': 3, 'needs-endpoint': 16, 'needs-upstream': 3, 'ready': 153} |
| Marketplace seed graphs | 35 (20 invalid with the full registry) | 50 (one per base pipeline) |
| Shipped node types used by templates | n/a | 71/76 (93.42%) |
| File templates run live | 24 run, 17 succeeded (tpl_exec.py) | 108 run: PASS: 101, needs-credentials (fails clearly): 3, needs-credentials/endpoint (refused up front: required config empty): 2, needs-credentials (MCP connection / agent token): 1, BLOCKED: api.github.com not on egress allowlist (live variant): 1 |

## Marketplace live successes per family (≥3 required)

| Family | PASS / bases |
|---|---|
| agents | 7 / 8 |
| audio | 18 / 18 |
| common | 10 / 10 |
| cross | 4 / 4 |
| video | 5 / 5 |
| wakeword | 5 / 5 |

## Catalog entries materialized by the live API and run (sample: 3 industry variants of distinct bases per family)

`POST /api/v1/pipelines/marketplace/materialize` (image catalog) → `POST /pipelines/run-async`, project `review-f20-templates`.

| Catalog entry | Family | Status label | Result | Run id | s | Error |
|---|---|---|---|---|---|---|
| `tpl-agents-guardrail-approval-memory` | agents | ready | PASS | `39486a3304f745d193023fd80bf1c6c8` | 2.2 |  |
| `tpl-agents-structured-extract-validate` | agents | ready | PASS | `097ae34fd4de4f559dfcfab89979d043` | 2.6 |  |
| `tpl-agents-tool-router-memory` | agents | ready | PASS | `e82c0706601449be80bd51d82ca34f35` | 2.0 |  |
| `tpl-audio-classify-yamnet` | audio | ready | PASS | `9d0a001263e54d5bb02de709f23c8d7d` | 24.2 |  |
| `tpl-audio-dataset-balance-version` | audio | ready | PASS | `0f722c607d7b4587a12c0fb263e9e3eb` | 2.0 |  |
| `tpl-audio-embeddings` | audio | ready | PASS | `d66cbff835d843d9b63e99af850cbed7` | 50.5 |  |
| `tpl-common-asr-captions` | common | ready | PASS | `eb7aba70d6c0464fb91f52beaef57b1d` | 2.2 |  |
| `tpl-common-asr-pii-redact` | common | ready | PASS | `316d5547b2a547cbb389761eede0a374` | 2.1 |  |
| `tpl-common-branch-merge-error` | common | ready | PASS | `be0d668da2154589a5590317e3ec1939` | 2.1 |  |
| `tpl-cross-call-analytics` | cross | ready | PASS | `2f1c8bd9628942b7981fa27862e47133` | 2.1 |  |
| `tpl-cross-meeting-notes-memory` | cross | ready | PASS | `ff211b5e02964cda93f999c7cd596108` | 2.1 |  |
| `tpl-cross-tts-asr-roundtrip` | cross | ready | PASS | `79b746c3694745f58cf7312662548c12` | 28.2 |  |
| `tpl-video-action-recognition` | video | ready | PASS | `081cc7d4c0074675aeed58fc4b2ead1c` | 18.4 |  |
| `tpl-video-scene-clips` | video | ready | PASS | `a3a881507fe34302a1f52ce8ea6e88a1` | 4.1 |  |
| `tpl-video-transcribe-captions` | video | ready | PASS | `0894e9b60c724df08a977762ecb64b0e` | 12.1 |  |
| `tpl-wakeword-data-gen` | wakeword | ready | PASS | `671b43c02b764b46ab35cac150524b7e` | 2.1 |  |
| `tpl-wakeword-features` | wakeword | ready | PASS | `f23ba0ecc9bc4eb19c19a2c2fb8ec65d` | 2.1 |  |
| `tpl-wakeword-train-export` | wakeword | ready | PASS | `c34b5d5ef8bc4cbe8affcd620391e90a` | 8.2 |  |

Per family PASS / sampled: agents 3/3, audio 3/3, common 3/3, cross 3/3, video 3/3, wakeword 3/3

## Example 06 shards removed

The five per-label shards `examples/06_speech_commands_e2e/pipeline_preprocess_{no,up,down,go,stop}.graph.json` appended to dataset version v1, which immutable dataset versions refuse once any run references it (live runs 6589c565, c6b5b7ab, 4fdaf940, 14e18cef, be2a7d5f). F20.14 made `pipeline_preprocess.graph.json` one all-labels run; preprocess → train → infer then succeeded live (see rows below).

## Per-template results

Overrides: marketplace seeds write to `workspace/{datasets/output,artifacts}/review-f20-templates/<slug>`; trainer epochs capped at 2; `video_ingest.path` → `workspace/f20_stage/video-demo` (same 651640-byte clip that `examples/31_video_demo/data/clip.mp4` now ships). Examples run as shipped otherwise. Runs interrupted by API restarts during the F19 rebuilds were retried automatically after the registry was back at 76 node types; those retries are listed under `transient_attempts` in the raw results. Column "old image" is the earlier sweep on the pre-rebuild image, for comparison.

| Template | Validates live | Result | Run id | s | Error / note | old image |
|---|---|---|---|---|---|---|
| `examples/templates/marketplace/tpl-agents-agent-loop.graph.json` | yes | PASS | `3dfa0a09a1d94916a946a404a65e447d` | 6.1 |  | failed |
| `examples/templates/marketplace/tpl-agents-email-alert.graph.json` | yes | PASS | `a56270d2d56046f98bb6e3a21c275957` | 2.2 |  | failed |
| `examples/templates/marketplace/tpl-agents-guarded-reply-memory.graph.json` | yes | PASS | `796db10f7fc447169b722f4d89d96eaa` | 2.1 |  | failed |
| `examples/templates/marketplace/tpl-agents-guardrail-approval-memory.graph.json` | yes | PASS | `407a83217bd94c8f85cbb52412fd17d4` | 2.1 |  | succeeded |
| `examples/templates/marketplace/tpl-agents-local-llm-chat.graph.json` | yes | PASS | `186ca3ab14354d9bb419c51d8fb0e000` | 2.1 |  | failed |
| `examples/templates/marketplace/tpl-agents-structured-extract-validate.graph.json` | yes | PASS | `e05b84fcae4d4a81b1b1c51929c47a6b` | 2.1 |  | succeeded |
| `examples/templates/marketplace/tpl-agents-tool-router-mcp.graph.json` | yes | needs-credentials (MCP connection / agent token) | `62d6471d11b741eb85fa5171aa2f2727` | 2.1 | mcp_tool_call: the platform requires auth for MCP tools — set config.connection_id to a credential of kind 'graphyn_mcp' (agent token) or se | failed |
| `examples/templates/marketplace/tpl-agents-tool-router-memory.graph.json` | yes | PASS | `85ddb81c51b24fe2ac4969fb15854a78` | 2.1 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-classify-yamnet.graph.json` | yes | PASS | `fbd348618a4944448c96797672c503e7` | 24.7 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-dataset-balance-version.graph.json` | yes | PASS | `ecf3f560df614bee8eb4f1332fcfa5c4` | 2.1 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-embeddings.graph.json` | yes | PASS | `45f4ce916db1415a822af3646ab2ce8f` | 56.5 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-kws-edge-tflite.graph.json` | yes | PASS | `91cbc4e45dab4fd681feb38af8819807` | 26.3 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-kws-train.graph.json` | yes | PASS | `eb4d95d7e55545cbbb7f4cee6439b5d8` | 28.3 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-podcast-leveling.graph.json` | yes | PASS | `190446580ed8489bb85c45d30e18d48c` | 2.0 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-quality-gate-export.graph.json` | yes | PASS | `0784c9a72ca047b2aac8c1e8550ba1ed` | 2.2 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-room-simulation-augment.graph.json` | yes | PASS | `303363c27a5d41d1a2eadaa7f3d0cb41` | 4.0 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-rule-annotate.graph.json` | yes | PASS | `20c33a37f39b43e0adae565fba2b12c5` | 2.0 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-sound-event-detection.graph.json` | yes | PASS | `f2fe34deca634b5ea55f96e4d20abee8` | 20.3 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-sound-event-train.graph.json` | yes | PASS | `f7ec838a1109407284c01732871fadc6` | 14.1 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-sound-generation.graph.json` | yes | PASS | `0cebc9d7f2ea43b0813e691e0873b699` | 131.1 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-speaker-id-train.graph.json` | yes | PASS | `430a3ea669d04d3c870ff37c702dbeda` | 24.2 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-speaker-separation.graph.json` | yes | PASS | `c67837a1af7545fea74f3957edfa1f74` | 44.4 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-speech-enhancement.graph.json` | yes | PASS | `b9a882a1f12d4d6d977d0261792b832a` | 4.1 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-stream-monitor.graph.json` | yes | PASS | `4f849eb2aca246339f4fda6e1166d71d` | 2.1 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-tts-dataset.graph.json` | yes | PASS | `b84e22496f774c6f8b572e31af226bb4` | 28.2 |  | succeeded |
| `examples/templates/marketplace/tpl-audio-voice-conversion.graph.json` | yes | PASS | `2ea7233429a14a6e9aacfc760a25f162` | 269.8 |  | succeeded |
| `examples/templates/marketplace/tpl-common-asr-captions.graph.json` | yes | PASS | `9eafad7c3a484b35940194b621a51c4d` | 2.0 |  | succeeded |
| `examples/templates/marketplace/tpl-common-asr-pii-redact.graph.json` | yes | PASS | `64fcf7cafc524dd2977b03a5ff56bcde` | 2.1 |  | succeeded |
| `examples/templates/marketplace/tpl-common-asr-word-alignment.graph.json` | yes | PASS | `dca3b0bd6b8b43808d35200168c5e990` | 2.1 |  | succeeded |
| `examples/templates/marketplace/tpl-common-branch-merge-error.graph.json` | yes | PASS | `c14a2a48b9284404bef339e55a9be582` | 2.1 |  | succeeded |
| `examples/templates/marketplace/tpl-common-csv-transform.graph.json` | yes | PASS | `8d82a1fa60a64d1b8322db92329f23d7` | 2.1 |  | failed |
| `examples/templates/marketplace/tpl-common-dataset-report-email.graph.json` | yes | PASS | `8efbfd7de22c4cfeab806f5e83a43846` | 2.0 |  | succeeded |
| `examples/templates/marketplace/tpl-common-doc-chunk-store.graph.json` | yes | PASS | `f8035cb71d1f43f887af5858482b6134` | 2.0 |  | succeeded |
| `examples/templates/marketplace/tpl-common-http-poll-transform.graph.json` | yes | PASS | `aea39b07072d4e8780e5b05df48dc596` | 2.2 |  | succeeded |
| `examples/templates/marketplace/tpl-common-speaker-embeddings.graph.json` | yes | PASS | `5da7e322cb494b50882ddc1b0a24ce1b` | 28.3 |  | succeeded |
| `examples/templates/marketplace/tpl-common-train-track-experiment.graph.json` | yes | PASS | `c951b0913c764273bbcc14472a3171ca` | 14.1 |  | succeeded |
| `examples/templates/marketplace/tpl-cross-call-analytics.graph.json` | yes | PASS | `51793d2e55614fd3bd3520001aebc0d4` | 2.0 |  | succeeded |
| `examples/templates/marketplace/tpl-cross-meeting-notes-memory.graph.json` | yes | PASS | `1c9a66df4a0b4251bc53438d4827e09f` | 2.0 |  | succeeded |
| `examples/templates/marketplace/tpl-cross-tts-asr-roundtrip.graph.json` | yes | PASS | `210a9b9bed084e1a8af0a92b4e90f807` | 6.1 |  | succeeded |
| `examples/templates/marketplace/tpl-cross-video-audio-fusion.graph.json` | yes | PASS | `453c3c187ee64f968ef893a14d2431ff` | 125.0 |  | succeeded |
| `examples/templates/marketplace/tpl-video-action-recognition.graph.json` | yes | PASS | `e61a382edbbe4ff08153f914179f3206` | 18.5 |  | succeeded |
| `examples/templates/marketplace/tpl-video-frame-captions-local-vlm.graph.json` | yes | PASS | `8e886832216a4b24876c860573c0d5db` | 6.1 |  | failed |
| `examples/templates/marketplace/tpl-video-scene-clips.graph.json` | yes | PASS | `894e735aa1a148e28466243ff10f8908` | 4.1 |  | succeeded |
| `examples/templates/marketplace/tpl-video-transcribe-captions.graph.json` | yes | PASS | `bfdf10ee38f84b65bec9d09611830965` | 2.1 |  | succeeded |
| `examples/templates/marketplace/tpl-video-zero-shot-tagging.graph.json` | yes | PASS | `5c852a7df38541699d39cb791b4e664c` | 8.1 |  | succeeded |
| `examples/templates/marketplace/tpl-wakeword-data-gen.graph.json` | yes | PASS | `e83dc0244a854d4882d142e86c6239f3` | 42.4 |  | succeeded |
| `examples/templates/marketplace/tpl-wakeword-detect.graph.json` | yes | PASS | `e9008de59f4f4002a5ad0f9a47dbffad` | 161.1 |  | failed |
| `examples/templates/marketplace/tpl-wakeword-features.graph.json` | yes | PASS | `bc1924c1c86b4557a7f23cd7c31c554f` | 32.3 |  | failed |
| `examples/templates/marketplace/tpl-wakeword-train-export.graph.json` | yes | PASS | `0a6f708ff88e45d2bc45e6c135198f8d` | 34.5 |  | failed |
| `examples/templates/marketplace/tpl-wakeword-train-int8-detect.graph.json` | yes | PASS | `1411526b5fe545559b2ae16bfb840509` | 195.3 |  | failed |
| `examples/templates/audio-classification.graph.json` | yes | PASS | `2924877a6a614557b34b973ad458a39a` | 24.3 |  | succeeded |
| `examples/templates/audio-quality-check.graph.json` | yes | PASS | `2ff4a88b764940eb817eaacc9312bc3d` | 12.2 |  | succeeded |
| `examples/templates/basic-wakeword.graph.json` | yes | PASS | `634e472b88284bcaa584ac544bcafbaa` | 8.1 |  | succeeded |
| `examples/templates/call-analytics.graph.json` | yes | PASS | `b982ddb25076494f83042ce328a1179e` | 2.0 |  | failed |
| `examples/templates/captions.graph.json` | yes | PASS | `c1652b7d79724665a8f75217782f8331` | 2.1 |  | succeeded |
| `examples/templates/doc-rag-ingest.graph.json` | yes | PASS | `b21f8dc85139494dbc82a7a20e1e27ee` | 2.0 |  | succeeded |
| `examples/templates/edge-deploy.graph.json` | yes | PASS | `2c34ff2c2cc44a558669a93c567c1f3e` | 2.1 |  | runner_error |
| `examples/templates/meeting-crm.graph.json` | yes | PASS | `f2fd3eecd5f74e779e9af7b9ed59b63f` | 2.0 |  | failed |
| `examples/templates/podcast-leveling.graph.json` | yes | PASS | `d5e9cca0f38b42279798aa39bd010922` | 22.2 |  | succeeded |
| `examples/templates/speech-commands-e2e-prepare.graph.json` | yes | PASS | `814c2e9ddf0d4b38be9125b6a5db6012` | 121.2 |  | succeeded |
| `examples/templates/speech-recognition.graph.json` | yes | PASS | `e4c8f138783b467fad6db6f2bfe54bcd` | 20.3 |  | succeeded |
| `examples/01_wake_word/pipeline.graph.json` | yes | PASS | `bb0b76489fb44998a85838d1395abb75` | 16.2 |  | succeeded |
| `examples/01_wake_word/pipeline_background.graph.json` | yes | PASS | `043e6713a1a04479a70c7419d81f1447` | 18.2 |  | succeeded |
| `examples/02_speech_commands/pipeline.graph.json` | yes | PASS | `0ec159d224a940ec814af1a352dcca21` | 20.3 |  | succeeded |
| `examples/02_speech_commands/pipeline_down.graph.json` | yes | PASS | `00191a03a320431badaa73147dbbad66` | 24.4 |  | succeeded |
| `examples/02_speech_commands/pipeline_go.graph.json` | yes | PASS | `769972c8c3f24bd7915b8a0e19d70819` | 24.3 |  | succeeded |
| `examples/02_speech_commands/pipeline_no.graph.json` | yes | PASS | `475bb633732b4f30990a486861179231` | 22.3 |  | succeeded |
| `examples/02_speech_commands/pipeline_stop.graph.json` | yes | PASS | `633927f6324b49ceb6f9fe33acc4ab1d` | 22.2 |  | succeeded |
| `examples/02_speech_commands/pipeline_up.graph.json` | yes | PASS | `608f4589d03c40459dfc916957ff1090` | 22.2 |  | succeeded |
| `examples/03_environmental_sounds/pipeline.graph.json` | yes | PASS | `c6bdb70b5edd46d2acb58f5487b8540e` | 14.3 |  | succeeded |
| `examples/03_environmental_sounds/pipeline_bird.graph.json` | yes | PASS | `95e5e5cc10804740b6ef164b22a23168` | 14.2 |  | succeeded |
| `examples/03_environmental_sounds/pipeline_cat.graph.json` | yes | PASS | `da9e9a5fbe894df2827438c0f0c5f346` | 14.2 |  | succeeded |
| `examples/03_environmental_sounds/pipeline_happy.graph.json` | yes | PASS | `b92bf15d53ff4bc0a09a908e2a57abbf` | 16.1 |  | succeeded |
| `examples/03_environmental_sounds/pipeline_house.graph.json` | yes | PASS | `c494a1ad3bf24d6085a3a9abc37d05e0` | 16.2 |  | succeeded |
| `examples/04_speaker_verification/pipeline.graph.json` | yes | PASS | `c0c4673aa92040bfb9facbb35744462a` | 2.1 |  | succeeded |
| `examples/04_speaker_verification/pipeline_speaker_002.graph.json` | yes | PASS | `3ebd6d5faf22428bb97863d1d9cd7704` | 2.1 |  | succeeded |
| `examples/04_speaker_verification/pipeline_speaker_003.graph.json` | yes | PASS | `876f93cb5a63414e8f00c3c5298b8a51` | 2.1 |  | succeeded |
| `examples/04_speaker_verification/pipeline_speaker_004.graph.json` | yes | PASS | `4d3460f96dad464a9f3bfdb36b973257` | 2.1 |  | succeeded |
| `examples/04_speaker_verification/pipeline_speaker_005.graph.json` | yes | PASS | `c032e84a60a146e5aa7154101d26ea50` | 2.1 |  | succeeded |
| `examples/04_speaker_verification/pipeline_speaker_006.graph.json` | yes | PASS | `ef3acb649f7f4758ad15851bbf90322a` | 2.1 |  | succeeded |
| `examples/05_speech_enhancement/pipeline.graph.json` | yes | PASS | `c80a3cfb3fb8443d846fc899c7229638` | 10.1 |  | succeeded |
| `examples/05_speech_enhancement/pipeline_degraded.graph.json` | yes | PASS | `73af46910c1f43b0a5f193b5e83224dc` | 16.2 |  | succeeded |
| `examples/06_speech_commands_e2e/pipeline_infer.graph.json` | yes | PASS | `822edc117b0f4bf1a3410ff618ff3ca4` | 20.2 |  | runner_error |
| `examples/06_speech_commands_e2e/pipeline_preprocess.graph.json` | yes | PASS | `7fb4fc347ba6400ab3a0e8dedbae6729` | 147.3 |  | succeeded |
| `examples/06_speech_commands_e2e/pipeline_train_ml.graph.json` | yes | PASS | `10b8087960fc4e099098e21ed2201941` | 107.1 |  | runner_error |
| `examples/09_parallel_execution/pipeline.graph.json` | yes | PASS | `02a15d6b8e7a48589dcdf997be7908a3` | 50.6 |  | succeeded |
| `examples/10_resumable_pipeline/pipeline.graph.json` | yes | PASS | `e508d00497ad417ea14f39dab95f468f` | 18.4 |  | succeeded |
| `examples/12_conditional_branching/pipeline.graph.json` | yes | PASS | `1dde739f746743589331e407d21772fb` | 14.1 |  | succeeded |
| `examples/18_pipeline_composition/augmentation.graph.json` | yes | PASS | `486a7a4449a24d24913684355d6d93b0` | 2.1 |  | succeeded |
| `examples/18_pipeline_composition/composed.graph.json` | yes | PASS | `b2cdd6debdd5498a9b71ddbe091220c8` | 8.1 |  | succeeded |
| `examples/18_pipeline_composition/preprocessing.graph.json` | yes | PASS | `a2401628c5fc410ea7aede34a9b6f012` | 6.2 |  | succeeded |
| `examples/19_capability_scheduling/edge_inference.graph.json` | yes | PASS | `532e1521b86246baac3279ce5ecd4b9c` | 2.1 |  | failed |
| `examples/22_call_analytics/pipeline.graph.json` | yes | PASS | `677e9dc889394018b21b7c019fb8f5b1` | 2.1 |  | succeeded |
| `examples/22_call_analytics/pipeline.live.graph.json` | yes | needs-credentials/endpoint (refused up front: required config empty) | `-` | - | {"error": {"code": "validation_failed", "message": "[http_webhook_6] HttpWebhookNode: config.url (or connection_id) is required (completion  | failed |
| `examples/23_meeting_crm/pipeline.graph.json` | yes | PASS | `d36a0ff107384664aebaba861fec7334` | 2.1 |  | succeeded |
| `examples/23_meeting_crm/pipeline.live.graph.json` | yes | needs-credentials/endpoint (refused up front: required config empty) | `-` | - | {"error": {"code": "validation_failed", "message": "[http_webhook_5] HttpWebhookNode: config.url (or connection_id) is required (completion  | failed |
| `examples/24_captions/pipeline.graph.json` | yes | PASS | `9c2735907ea94293b149525ebe306209` | 2.0 |  | succeeded |
| `examples/24_captions/pipeline.live.graph.json` | yes | needs-credentials (fails clearly) | `715140a1f8084457b79bc943bdc8b6b0` | 2.1 | RuntimeError: AsrTranscribeNode: provider='deepgram' requires secret/env DEEPGRAM_API_KEY. Store it with `graphyn secrets set …` or export t | failed |
| `examples/25_doc_rag_ingest/pipeline.graph.json` | yes | PASS | `28b26309c6894ec0a005929e9802c1d0` | 2.1 |  | succeeded |
| `examples/25_doc_rag_ingest/pipeline.live.graph.json` | yes | PASS | `f71a5c9208df48d79f2ef5c11e0c7fde` | 2.0 |  | succeeded |
| `examples/26_nightly_compliance/pipeline.graph.json` | yes | PASS | `43707d8ae21c497d86579b383a3bfdb5` | 2.1 |  | succeeded |
| `examples/26_nightly_compliance/pipeline.live.graph.json` | yes | needs-credentials (fails clearly) | `49161253e8f54a39a195a1164db2af83` | 2.0 | RuntimeError: AsrTranscribeNode: provider='openai_compat' requires a connection or secret/env OPENAI_API_KEY (or GROQ_API_KEY when base_url  | failed |
| `examples/27_github_triage/pipeline.graph.json` | yes | PASS | `a4cd11b8c7d44a27aa2ec11108cc7105` | 2.1 |  | succeeded |
| `examples/27_github_triage/pipeline.live.graph.json` | yes | BLOCKED: api.github.com not on egress allowlist (live variant) | `34eac9baab084115a2123c2c36a8061c` | 2.0 | HTTP egress blocked: host 'api.github.com' is not on GRAPHYN_HTTP_EGRESS_ALLOWLIST. | failed |
| `examples/28_asr_eval_merge/pipeline.graph.json` | yes | PASS | `3cb542d91ada47e9ae780150c60c35c3` | 2.1 |  | succeeded |
| `examples/28_asr_eval_merge/pipeline.live.graph.json` | yes | needs-credentials (fails clearly) | `006df839ff734cb6a230403d7818cad0` | 2.1 | RuntimeError: AsrTranscribeNode: provider='openai_compat' requires a connection or secret/env OPENAI_API_KEY (or GROQ_API_KEY when base_url  | failed |
| `examples/29_distributed_placement/pipeline.graph.json` | yes | PASS | `f40f7d8de49b49cc851d481d87a54433` | 2.1 |  | runner_error |
| `examples/30_edge_deploy/pipeline.graph.json` | yes | PASS | `8960c2c121574adeac1054ebd7be7670` | 4.0 |  | runner_error |
