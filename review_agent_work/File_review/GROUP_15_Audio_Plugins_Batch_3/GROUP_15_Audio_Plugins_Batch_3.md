# Group Review Index — 15: Audio Plugins Batch 3

**Files reviewed:** 8
**Total findings:** 34 (CRITICAL: 1 | HIGH: 14 | MEDIUM: 15 | LOW: 4)
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| segmenter_nodes.md | MEDIUM | 3 | `_segment_event` crashes on zero-length audio via librosa ValueError; `_segment_vad` silently returns empty output for stereo audio |
| speaker_separator_nodes.md | HIGH | 2 | `.numpy()` on GPU tensor in `_separate_speechbrain` crashes on any CUDA system; stereo audio crashes both backends |
| speech_enhancer_nodes.md | HIGH | 1 | `.numpy()` on GPU tensor in `_denoise_deepfilter` crashes on any CUDA system |
| speech_synthesizer_nodes.md | CRITICAL | 1 | `_synthesize_espeak` has a duplicate NamedTemporaryFile bug — eSpeak writes to temp file #1 but code reads from temp file #2 (empty), causing data loss and temp file leak on every call |
| stream_ingest_nodes.md | HIGH | 2 | `asyncio.run()` in `_capture_websocket` crashes when called from an async context (FastAPI, async executor) |
| stream_processor_nodes.md | HIGH | 1 | `process()` raises AttributeError if `setup()` was not called; stereo audio produces 2D windows that silently corrupt downstream processing |
| voice_converter_nodes.md | HIGH | 2 | `.numpy()` on GPU tensor in `_convert_speechbrain` crashes on any CUDA system; lazy model loading has a race condition in concurrent use |
| environment_simulator_nodes.md | HIGH | 2 | The "outdoor" preset crashes on every call due to physically impossible RT60/room-size combination causing `pra.inverse_sabine` to raise ValueError |

---

## Priority Findings (CRITICAL and HIGH only)

**[CRITICAL] speech_synthesizer_nodes.md — `_synthesize_espeak` — Duplicate NamedTemporaryFile: eSpeak writes to temp file #1 but code reads from temp file #2 (empty); temp file #1 leaks on every call; synthesized audio is never returned**

**[HIGH] speaker_separator_nodes.md — `_separate_speechbrain` — `.numpy()` on GPU tensor raises RuntimeError on any CUDA system**

**[HIGH] speaker_separator_nodes.md — `setup` — `except ImportError: pass` silently swallows model load failures, leaving `_pyannote_pipeline=None` and causing model reload on every process() call**

**[HIGH] speaker_separator_nodes.md — `_separate_pyannote` — Stereo audio produces wrong tensor shape `(1, N, 2)` instead of `(1, N)` for pyannote, causing crash or wrong diarization**

**[HIGH] speaker_separator_nodes.md — `_separate_speechbrain` — Stereo audio produces wrong tensor shape, causing crash inside SpeechBrain**

**[HIGH] speech_enhancer_nodes.md — `_denoise_deepfilter` — `.numpy()` on GPU tensor raises RuntimeError on any CUDA system**

**[HIGH] speech_synthesizer_nodes.md — `_synthesize_coqui` — Lazy model loading has no thread safety; concurrent calls may load model twice; no setup-time validation**

**[HIGH] stream_ingest_nodes.md — `_capture_websocket` — `asyncio.run()` raises RuntimeError when called from an existing event loop (FastAPI, async executor, Jupyter)**

**[HIGH] stream_ingest_nodes.md — `_capture_microphone` — `sd.wait()` blocks indefinitely if audio device hangs; no timeout**

**[HIGH] stream_processor_nodes.md — `process` — AttributeError if `setup()` not called; no guard in process()**

**[HIGH] stream_processor_nodes.md — `process` — Stereo audio produces 2D windows that silently corrupt downstream processing**

**[HIGH] voice_converter_nodes.md — `_convert_speechbrain` — `.numpy()` on GPU tensor raises RuntimeError on any CUDA system**

**[HIGH] voice_converter_nodes.md — `_convert_speechbrain` — Lazy model loading has no thread safety; concurrent calls may load model twice**

**[HIGH] environment_simulator_nodes.md — `_simulate` — "outdoor" preset crashes on every call: `pra.inverse_sabine(0.05, [50,50,10])` produces absorption > 1.0 → ValueError**

**[HIGH] environment_simulator_nodes.md — `_simulate` — No lower-bound clamp on mic/source positions; negative or zero positions crash pyroomacoustics**

---

## Most Dangerous File

**speech_synthesizer_nodes.md** — Contains a CRITICAL bug where `_synthesize_espeak` creates two temporary files but writes audio to the first and reads from the second (empty), causing complete data loss and a temp file resource leak on every eSpeak call. This is a logic error that makes the eSpeak backend entirely non-functional.
