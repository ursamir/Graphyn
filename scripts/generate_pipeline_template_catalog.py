#!/usr/bin/env python3
"""Generate the Graphyn pipeline template marketplace catalog.

Only shipped packs are advertised (Audio, Common, Agents, Video, WakeWord).
RAG / Vision / TinyML / MLOps are not shipped (removed packs) and have no
templates.

Every catalog entry is built from a *base pipeline* defined below with an
explicit node chain, explicit edges (``edges_hint``) and working configs.
Industry variants reuse the base pipeline graph unchanged and differ only in
labels/tags/parameters, so validating + live-running the base proves every
variant (``metadata_extra.base_template`` names the base).

Statuses:
  ``ready``              — runs out of the box on the bundled seed data.
  ``needs-credentials``  — validates; the run stops with a clear
                           "configure credential X" error until the operator
                           adds the named credential / endpoint.
  ``needs-endpoint``     — validates; runs once the named local service is
                           reachable (e.g. Ollama allowed by the egress policy);
                           until then the run fails with the egress/connection error.
  ``needs-upstream``     — runs once the named upstream template has produced
                           its artifact (e.g. a trained wake-word model).

Live verification evidence (run ids) is merged from
``docs/PIPELINE_TEMPLATE_VERIFICATION.json`` when present.

Usage::

    python scripts/generate_pipeline_template_catalog.py            # catalog + seed graphs
    python scripts/generate_pipeline_template_catalog.py --check    # exit 1 if any entry fails to validate
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "docs" / "PIPELINE_TEMPLATE_CATALOG.json"
VERIFICATION = REPO / "docs" / "PIPELINE_TEMPLATE_VERIFICATION.json"
SEED_DIR = REPO / "examples" / "templates" / "marketplace"
SHIPPED_PACKS = ("Audio", "Common", "Agents", "Video", "WakeWord")
REMOVED_PACKS = ("RAG", "Vision", "TinyML", "MLOps")

DEFAULT_TOOLS = [
    "search_templates", "get_template", "materialize_template",
    "validate_graph", "save_pipeline", "execute_pipeline",
]


def N(node_type: str, config: dict | None = None, role: str = "") -> dict:
    step: dict[str, Any] = {"node_type": node_type}
    if config:
        step["config_overrides"] = config
    if role:
        step["role"] = role
    return step


def E(src: int, dst: int, src_port: str = "output", dst_port: str = "input") -> dict:
    return {"src_id": f"n{src}", "src_port": src_port, "dst_id": f"n{dst}", "dst_port": dst_port}


def chain_edges(n: int) -> list[dict]:
    return [E(i, i + 1) for i in range(n - 1)]


# ── Shared building blocks ────────────────────────────────────────────────────

INGEST = N("dataset_ingest", {"source_type": "filesystem", "recursive": True, "limit": 8}, "ingest")
COND = N("audio_conditioner", {"target_sample_rate": 16000, "mono": True}, "condition")
ASR = N("asr_transcribe", {"provider": "local_whisper", "model": "tiny", "language": "en"}, "transcribe")
EXPORT = N("audio_exporter", {"format": "wav", "overwrite": True}, "export")


def kws_train_chain(front: list[dict]) -> tuple[list[dict], list[dict]]:
    """ingest → <front…> → features → dataset → model → train → evaluate."""
    nodes = [INGEST, *front,
             N("feature_frontend", {"feature_type": "log_mel", "n_mels": 40}, "features"),
             N("dataset_builder", {"fixed_length": 100}, "dataset"),
             N("model_builder", {"architecture": "ds_cnn", "filters": 32, "num_layers": 2}, "model"),
             N("trainer", {"epochs": 1, "batch_size": 8, "device": "cpu"}, "train"),
             N("evaluator", {}, "evaluate")]
    k = len(front)
    feat, ds, mb, tr, ev = k + 1, k + 2, k + 3, k + 4, k + 5
    edges = chain_edges(feat + 1) + [
        E(feat, ds), E(ds, mb),
        E(mb, tr, "output", "model"), E(ds, tr, "output", "dataset"),
        E(tr, ev, "output", "model_artifact"), E(ds, ev, "output", "dataset"),
    ]
    return nodes, edges


def base(**kw) -> dict:
    kw.setdefault("status", "ready")
    kw.setdefault("industries", [])
    kw.setdefault("parameters", {})
    kw.setdefault("requires", [])
    return kw


def build_bases() -> list[dict]:
    B: list[dict] = []

    # ── Audio ────────────────────────────────────────────────────────────────
    nodes, edges = kws_train_chain([COND, N("segmenter", {"mode": "fixed", "window_ms": 1000}, "segment"),
                                    N("augmentation_pipeline", {"copies_per_sample": 1}, "augment")])
    B.append(base(slug="audio-kws-train", family="audio", pack="Audio", packs=["Audio", "Common"],
                  name="Keyword spotting: train + evaluate",
                  description="Ingest labelled keyword clips, condition, segment, augment, log-mel features, "
                              "build a dataset, train a DS-CNN and evaluate it.",
                  modality=["audio"], lifecycle=["prep", "train", "eval"], tags=["kws", "train"],
                  industries=["smart-home", "automotive", "retail", "industrial", "healthcare"],
                  nodes=nodes, edges=edges))
    n2, e2 = kws_train_chain([COND, N("segmenter", {"mode": "fixed", "window_ms": 1000}, "segment")])
    tr = len(n2) - 2
    n2 = n2 + [N("edge_optimizer", {"backend": "tflite", "quantization": "int8", "representative_samples": 16}, "optimize"),
               N("deployment_packager", {"target": "mobile", "selftest_samples": 2}, "package")]
    e2 = e2 + [E(tr, len(n2) - 2), E(len(n2) - 2, len(n2) - 1)]
    B.append(base(slug="audio-kws-edge-tflite", family="audio", pack="Audio", packs=["Audio", "Common"],
                  name="Keyword spotting → INT8 TFLite edge package",
                  description="Train a keyword model, quantize it to INT8 TFLite and package it with an "
                              "inference script for mobile/edge.",
                  modality=["audio"], lifecycle=["train", "deploy"], tags=["kws", "edge", "tflite"],
                  industries=["smart-home", "automotive", "wearables"], nodes=n2, edges=e2))
    n3, e3 = kws_train_chain([COND])
    B.append(base(slug="audio-speaker-id-train", family="audio", pack="Audio", packs=["Audio", "Common"],
                  name="Speaker identification: train + evaluate",
                  description="Train a closed-set speaker classifier on per-speaker folders and evaluate it.",
                  modality=["audio"], lifecycle=["prep", "train", "eval"], tags=["speaker", "train"],
                  industries=["security", "callcenter", "banking"], nodes=n3, edges=e3))
    n4, e4 = kws_train_chain([COND, N("audio_quality_gate", {"min_snr_db": 0.0, "check_bandwidth": False}, "quality")])
    B.append(base(slug="audio-sound-event-train", family="audio", pack="Audio", packs=["Audio", "Common"],
                  name="Environmental sound classifier: train + evaluate",
                  description="Quality-gate environmental sound clips, extract features, train and evaluate a classifier.",
                  modality=["audio"], lifecycle=["prep", "train", "eval"], tags=["sed", "environmental", "train"],
                  industries=["industrial", "smart-city", "security"], nodes=n4, edges=e4))
    B.append(base(slug="audio-quality-gate-export", family="audio", pack="Audio", packs=["Audio"],
                  name="Audio quality gate → curated export",
                  description="Condition clips, reject low-SNR / clipped / silent audio and export a "
                              "train/val/test split of the accepted clips.",
                  modality=["audio"], lifecycle=["prep"], tags=["quality", "curation"],
                  industries=["callcenter", "media", "healthcare"],
                  nodes=[INGEST, COND, N("audio_quality_gate", {"min_snr_db": 0.0, "check_bandwidth": False}, "quality"), EXPORT],
                  edges=chain_edges(4)))
    B.append(base(slug="audio-speech-enhancement", family="audio", pack="Audio", packs=["Audio"],
                  name="Speech enhancement (spectral denoise) → export",
                  description="Denoise speech with spectral gating, quality-gate and export the cleaned clips.",
                  modality=["audio"], lifecycle=["prep"], tags=["enhancement", "denoise"],
                  industries=["callcenter", "media", "telehealth"],
                  nodes=[INGEST, COND, N("speech_enhancer", {"backend": "spectral", "denoise": True}, "enhance"),
                         N("audio_quality_gate", {"min_snr_db": 0.0, "check_bandwidth": False}, "quality"), EXPORT],
                  edges=chain_edges(5)))
    B.append(base(slug="audio-podcast-leveling", family="audio", pack="Audio", packs=["Audio"],
                  name="Podcast leveling (LUFS + compression + denoise)",
                  description="Loudness-normalise to -16 LUFS with compression and limiting, denoise, export.",
                  modality=["audio"], lifecycle=["prep"], tags=["enhancement", "podcast", "loudness"],
                  industries=["media", "education"],
                  nodes=[INGEST, N("audio_conditioner", {"normalize_method": "lufs", "target_lufs": -16.0,
                                                         "compress": True, "limiter": True}, "level"),
                         N("speech_enhancer", {"backend": "spectral"}, "enhance"), EXPORT],
                  edges=chain_edges(4)))
    B.append(base(slug="audio-sound-event-detection", family="audio", pack="Audio", packs=["Audio"],
                  name="Sound event detection (YAMNet) → annotated export",
                  description="Detect sound events with YAMNet (AudioSet classes) and export clips with event metadata.",
                  modality=["audio"], lifecycle=["infer", "label"], tags=["sed", "environmental", "yamnet"],
                  industries=["smart-city", "industrial", "security"],
                  nodes=[INGEST, COND, N("audio_event_detector", {"threshold": 0.2}, "detect"), EXPORT],
                  edges=chain_edges(4)))
    B.append(base(slug="audio-classify-yamnet", family="audio", pack="Audio", packs=["Audio", "Common"],
                  name="Audio classification (YAMNet) → predictions store",
                  description="Classify clips against the 521 AudioSet classes with YAMNet and store top-k predictions.",
                  modality=["audio"], lifecycle=["infer"], tags=["environmental", "classification", "yamnet"],
                  industries=["media", "smart-city", "research"],
                  nodes=[INGEST, COND, N("audio_classifier", {"top_k": 3}, "classify"),
                         N("object_store", {"operation": "put", "prefix": "predictions"}, "store")],
                  edges=chain_edges(4)))
    B.append(base(slug="audio-rule-annotate", family="audio", pack="Audio", packs=["Audio"],
                  name="Rule-based audio annotation → labelled export",
                  description="Attach rule-based labels (loudness / duration rules) to clips and export the annotated set.",
                  modality=["audio"], lifecycle=["label"], tags=["kws", "annotation"],
                  industries=["research", "healthcare"],
                  nodes=[INGEST, COND,
                         N("audio_annotator", {"annotation_mode": "auto", "auto_rules": [
                             {"field": "duration", "op": ">=", "value": 0.5, "label": "full_utterance"},
                             {"field": "duration", "op": "<", "value": 0.5, "label": "short_utterance"}]}, "annotate"),
                         EXPORT],
                  edges=chain_edges(4)))
    B.append(base(slug="audio-room-simulation-augment", family="audio", pack="Audio", packs=["Audio"],
                  name="Room acoustics simulation augmentation",
                  description="Convolve clips with simulated room impulse responses (pyroomacoustics) plus "
                              "gain/noise augmentation and export a far-field training set.",
                  modality=["audio"], lifecycle=["prep"], tags=["kws", "augmentation", "far-field"],
                  industries=["smart-home", "automotive", "conferencing"],
                  nodes=[INGEST, N("environment_simulator", {"preset": "room", "copies_per_sample": 1}, "simulate"),
                         N("augmentation_pipeline", {"copies_per_sample": 1}, "augment"), EXPORT],
                  edges=chain_edges(4)))
    B.append(base(slug="audio-tts-dataset", family="audio", pack="Audio", packs=["Audio"],
                  name="Synthetic speech dataset (MMS-TTS)",
                  description="Synthesize prompt phrases with Meta MMS-TTS, condition and export them as a dataset.",
                  modality=["audio", "text"], lifecycle=["prep"], tags=["tts", "synthetic"],
                  industries=["smart-home", "ivr", "accessibility"],
                  nodes=[N("speech_synthesizer", {"backend": "mms", "text": "turn on the kitchen lights"}, "synthesize"),
                         COND, EXPORT],
                  edges=chain_edges(3)))
    B.append(base(slug="audio-speaker-separation", family="audio", pack="Audio", packs=["Audio"],
                  name="Speaker separation (SepFormer) → per-speaker export",
                  description="Separate overlapped speech into per-speaker tracks with SpeechBrain SepFormer and export them.",
                  modality=["audio"], lifecycle=["prep"], tags=["speaker", "separation"],
                  industries=["callcenter", "meetings", "media"],
                  nodes=[INGEST, COND, N("speaker_separator", {"backend": "speechbrain", "num_speakers": 2}, "separate"), EXPORT],
                  edges=chain_edges(4)))
    B.append(base(slug="audio-voice-conversion", family="audio", pack="Audio", packs=["Audio"],
                  name="Voice conversion (kNN-VC) to a reference speaker",
                  description="Convert clips to a reference speaker's voice with kNN-VC (WavLM features) and export them.",
                  modality=["audio"], lifecycle=["prep"], tags=["speaker", "voice-conversion"],
                  industries=["media", "accessibility"],
                  nodes=[INGEST, N("voice_converter", {"backend": "knnvc",
                                                       "target_speaker": "workspace/datasets/input/speaker-verification/speaker_002"}, "convert"),
                         EXPORT],
                  edges=chain_edges(3)))
    B.append(base(slug="audio-embeddings", family="audio", pack="Audio", packs=["Audio", "Common"],
                  name="Audio embeddings (wav2vec2) → object store",
                  description="Compute mean-pooled wav2vec2 embeddings per clip and store them as JSON objects.",
                  modality=["audio"], lifecycle=["prep"], tags=["embeddings", "kws"],
                  industries=["search", "research"],
                  nodes=[INGEST, COND, N("embedding_generator", {"model": "wav2vec2"}, "embed"),
                         N("object_store", {"operation": "put", "prefix": "embeddings"}, "store")],
                  edges=chain_edges(4)))
    B.append(base(slug="audio-stream-monitor", family="audio", pack="Audio", packs=["Audio"],
                  name="Streaming audio windows → quality gate → export",
                  description="Stream a file (or microphone/URL) in 100 ms chunks, window it, quality-gate and export windows.",
                  modality=["audio"], lifecycle=["observe"], tags=["streaming", "monitoring"],
                  industries=["industrial", "security"],
                  nodes=[N("stream_ingest", {"source": "file_stream", "duration_s": 1.0}, "stream"),
                         N("stream_processor", {"window_ms": 500, "hop_ms": 250}, "window"),
                         N("audio_quality_gate", {"min_snr_db": 0.0, "check_bandwidth": False, "min_duration_s": 0.1}, "quality"),
                         EXPORT],
                  edges=chain_edges(4)))
    B.append(base(slug="audio-sound-generation", family="audio", pack="Audio", packs=["Audio"],
                  name="Text-to-audio generation (MusicGen) → export",
                  description="Generate short audio clips from a text prompt with MusicGen-small, condition and export.",
                  modality=["audio", "text"], lifecycle=["prep"], tags=["generation", "synthetic"],
                  industries=["media", "games"],
                  nodes=[N("audio_generator", {"model_size": "small", "duration_s": 2.0,
                                               "prompt": "gentle rain on a window"}, "generate"), COND, EXPORT],
                  edges=chain_edges(3)))
    B.append(base(slug="audio-dataset-balance-version", family="audio", pack="Audio", packs=["Audio", "Common"],
                  name="Feature dataset → class balancing → versioned snapshot",
                  description="Build a feature dataset, oversample minority classes and write a versioned dataset snapshot.",
                  modality=["audio"], lifecycle=["prep", "govern"], tags=["kws", "dataset", "versioning"],
                  industries=["smart-home", "healthcare"],
                  nodes=[INGEST, COND, N("feature_frontend", {"feature_type": "mfcc"}, "features"),
                         N("dataset_builder", {"fixed_length": 100}, "dataset"),
                         N("dataset_balancer", {"strategy": "oversample"}, "balance"),
                         N("dataset_versioner", {"version_tag": "v1", "overwrite": True}, "version")],
                  edges=chain_edges(6)))

    # ── Common ───────────────────────────────────────────────────────────────
    B.append(base(slug="common-asr-captions", family="common", pack="Common", packs=["Audio", "Common"],
                  name="Local Whisper ASR → SRT/VTT captions",
                  description="Transcribe with local faster-whisper (no API key) and export SRT, VTT and JSON captions.",
                  modality=["audio", "text"], lifecycle=["infer"], tags=["captions", "asr"],
                  industries=["media", "education", "accessibility"],
                  nodes=[INGEST, ASR, N("caption_export", {"formats": ["srt", "vtt", "json"]}, "captions")],
                  edges=chain_edges(3)))
    B.append(base(slug="common-asr-pii-redact", family="common", pack="Common", packs=["Audio", "Common"],
                  name="ASR → PII redaction (text + audio bleep) → store",
                  description="Transcribe locally, redact PII in text and bleep it in audio, gate, store the redacted transcripts.",
                  modality=["audio", "text"], lifecycle=["infer", "govern"], tags=["captions", "pii", "compliance"],
                  industries=["callcenter", "healthcare", "banking"],
                  nodes=[INGEST, COND, ASR, N("pii_redact", {"engine": "auto"}, "redact"),
                         N("eval_gate", {"check_empty_transcript": False, "fail_if_empty_list": False}, "gate"),
                         N("object_store", {"operation": "put", "prefix": "redacted"}, "store")],
                  edges=[E(0, 1), E(1, 2), E(2, 3, "output", "transcript"), E(1, 3, "output", "audio"),
                         E(3, 4, "transcript", "input"), E(4, 5)]))
    B.append(base(slug="common-asr-word-alignment", family="common", pack="Common", packs=["Audio", "Common"],
                  name="ASR + forced word alignment (MMS_FA)",
                  description="Transcribe locally then force-align words to audio with torchaudio MMS_FA for word timings.",
                  modality=["audio", "text"], lifecycle=["label"], tags=["captions", "alignment"],
                  industries=["media", "education"],
                  nodes=[INGEST, COND, ASR, N("alignment_node", {"language": "en", "level": "word"}, "align"), EXPORT],
                  edges=[E(0, 1), E(1, 2), E(1, 3, "output", "audio"), E(2, 3, "output", "transcripts"), E(3, 4)]))
    B.append(base(slug="common-doc-chunk-store", family="common", pack="Common", packs=["Common"],
                  name="Document parse + chunk → object store",
                  description="Parse local markdown/text, chunk by structure, gate non-empty and store chunks as objects.",
                  modality=["text"], lifecycle=["ingest"], tags=["docs", "chunking"],
                  industries=["support", "legal", "general"],
                  nodes=[N("doc_parse_chunk", {"path": "workspace/datasets/input/doc-rag-ingest", "max_chars": 800}, "parse"),
                         N("eval_gate", {"check_empty_transcript": False, "fail_if_empty_list": True}, "gate"),
                         N("object_store", {"operation": "put", "prefix": "chunks"}, "store")],
                  edges=chain_edges(3)))
    B.append(base(slug="common-csv-transform", family="common", pack="Common", packs=["Common"],
                  name="CSV read → python transform → CSV write",
                  description="Read a CSV, derive a column with python_code and write the result CSV.",
                  modality=["tabular"], lifecycle=["prep"], tags=["csv", "etl"],
                  industries=["general", "finance", "retail"],
                  nodes=[N("csv_table", {"operation": "read", "path": "datasets/input/csv-data-processing/sample.csv"}, "read"),
                         N("python_code", {"source": "src = inputs.get('input')\nrows = src.get('rows', src) if isinstance(src, dict) else (src if isinstance(src, (list, tuple)) or src is None else src.rows)\n"
                                                     "output = [dict(r, score_band=('high' if float(r.get('score') or 0) >= 50 else 'low')) for r in (rows or [])]\n"}, "transform"),
                         N("csv_table", {"operation": "write", "path": "artifacts/templates/csv-transform/out.csv"}, "write")],
                  edges=chain_edges(3)))
    B.append(base(slug="common-http-poll-transform", family="common", pack="Common", packs=["Common"],
                  name="Scheduled HTTP poll → JSON transform → store",
                  description="On a schedule, GET a public JSON API, pick fields with JSONPath and store the snapshot.",
                  modality=["text"], lifecycle=["observe"], tags=["http", "polling"],
                  industries=["general", "devops"],
                  nodes=[N("schedule_trigger", {"interval_s": 3600}, "tick"),
                         N("http_request", {"method": "GET",
                                            "url": "https://huggingface.co/api/models/facebook/mms-tts-eng"}, "fetch"),
                         N("json_transform", {"mappings": [{"from": "$.id", "to": "model"},
                                                           {"from": "$.downloads", "to": "downloads"}]}, "transform"),
                         N("object_store", {"operation": "put", "prefix": "poll"}, "store")],
                  edges=chain_edges(4)))
    B.append(base(slug="common-branch-merge-error", family="common", pack="Common", packs=["Common"],
                  name="Branch → transform / error-catch → merge → delay",
                  description="Route a payload with if_switch, transform one branch, catch errors on the other, merge and delay.",
                  modality=["text"], lifecycle=["orchestrate"], tags=["control-flow"],
                  industries=["general"],
                  nodes=[N("if_switch", {"expression": "True"}, "branch"), N("python_code", {"source": "output = {'ok': True}\n"}, "transform"),
                         N("error_catch", {}, "catch"), N("merge", {"mode": "append"}, "merge"),
                         N("wait_delay", {"seconds": 0.5}, "delay")],
                  edges=[E(0, 1, "true", "input"), E(0, 2, "false", "input"), E(1, 3, "output", "a"),
                         E(2, 3, "output", "b"), E(3, 4)]))
    n5, e5 = kws_train_chain([COND])
    n5 = n5 + [N("experiment_tracker", {"backend": "json", "experiment_name": "kws-baseline"}, "track")]
    e5 = e5 + [E(len(n5) - 2, len(n5) - 1)]
    B.append(base(slug="common-train-track-experiment", family="common", pack="Common", packs=["Audio", "Common"],
                  name="Train + evaluate + log experiment",
                  description="Train and evaluate a keyword model and log params/metrics/artifacts with the experiment tracker "
                              "(JSON run store; MLflow when tracking_uri is set).",
                  modality=["audio"], lifecycle=["train", "eval", "govern"], tags=["kws", "experiments"],
                  industries=["research", "smart-home"], nodes=n5, edges=e5))
    B.append(base(slug="common-speaker-embeddings", family="common", pack="Common", packs=["Audio", "Common"],
                  name="Speaker embeddings (ECAPA-TDNN) → object store",
                  description="Compute ECAPA-TDNN speaker embeddings (SpeechBrain, VoxCeleb) per clip and store them for "
                              "speaker search / verification.",
                  modality=["audio"], lifecycle=["prep"], tags=["speaker", "embeddings"],
                  industries=["security", "callcenter"],
                  nodes=[INGEST, COND, N("embedding_generator", {"model": "ecapa"}, "embed"),
                         N("object_store", {"operation": "put", "prefix": "speaker-embeddings"}, "store")],
                  edges=chain_edges(4)))
    B.append(base(slug="common-dataset-report-email", family="common", pack="Common", packs=["Audio", "Common"],
                  name="Dataset report → email (SMTP dry-run)",
                  description="Count clips per label with python_code and email the report (dry_run on: the message is "
                              "rendered and logged, not sent, until you turn dry_run off and configure SMTP).",
                  modality=["audio", "text"], lifecycle=["observe"], tags=["kws", "email", "report"],
                  industries=["general"],
                  nodes=[INGEST,
                         N("python_code", {"source": "items = inputs.get('input') or []\nper_label = {}\n"
                                                     "for s in items:\n"
                                                     "    lab = (s.get('label') if isinstance(s, dict) else s.label) or 'unlabelled'\n"
                                                     "    per_label[str(lab)] = per_label.get(str(lab), 0) + 1\n"
                                                     "output = {'total': len(items), 'per_label': per_label}\n"}, "report"),
                         N("send_email", {"to": "ops@example.com", "allowed_recipient_domains": ["example.com"],
                                          "subject": "Graphyn dataset report", "dry_run": True}, "email")],
                  edges=chain_edges(3)))

    # ── WakeWord ─────────────────────────────────────────────────────────────
    def ww_gen(model: str, phrase: str, n: int = 24, nv: int = 8) -> dict:
        return N("wakeword_data_gen", {"model_name": model, "output_dir": "workspace/models/wakeword", "target_phrases": [phrase], "n_samples": n,
                                       "n_samples_val": nv, "n_background_samples": 8,
                                       "n_background_samples_val": 2, "tts_backend": "auto"}, "generate")
    FEAT = N("wakeword_feature_extract", {"augment": True, "rounds": 1}, "features")
    TRAIN = N("wakeword_train", {"steps": 600, "device": "cpu"}, "train")
    B.append(base(slug="wakeword-data-gen", family="wakeword", pack="WakeWord", packs=["WakeWord"],
                  name="Wake word: synthetic positives + adversarial negatives",
                  description="Generate TTS positives for the wake phrase plus phonetically-similar adversarial negatives "
                              "and background clips (Piper VITS when espeak-ng is present, else MMS-TTS).",
                  modality=["audio"], lifecycle=["prep"], tags=["wakeword", "synthetic"],
                  industries=["smart-home", "automotive", "consumer-electronics"],
                  nodes=[ww_gen("hey_graphyn_gen", "hey graphyn")], edges=[]))
    B.append(base(slug="wakeword-features", family="wakeword", pack="WakeWord", packs=["WakeWord"],
                  name="Wake word: data → augmented ONNX features",
                  description="Generate clips, augment (RIR/noise/gain) and extract mel-spectrogram + speech embedding features.",
                  modality=["audio"], lifecycle=["prep"], tags=["wakeword", "features"],
                  industries=["smart-home", "automotive"],
                  nodes=[ww_gen("hey_graphyn_feat", "hey graphyn"), FEAT], edges=[E(0, 1, "run", "run")]))
    B.append(base(slug="wakeword-train-export", family="wakeword", pack="WakeWord", packs=["WakeWord"],
                  name="Wake word: data → features → train → ONNX",
                  description="End-to-end wake-word model: synthetic data, features, 3-phase training with threshold tuning, ONNX export.",
                  modality=["audio"], lifecycle=["prep", "train", "deploy"], tags=["wakeword", "train", "onnx"],
                  industries=["smart-home", "automotive", "wearables"],
                  nodes=[ww_gen("hey_graphyn", "hey graphyn"), FEAT, TRAIN,
                         N("wakeword_export_onnx", {"quantize": False}, "export")],
                  edges=[E(0, 1, "run", "run"), E(1, 2, "run", "run"), E(2, 3, "run", "run")]))
    B.append(base(slug="wakeword-train-int8-detect", family="wakeword", pack="WakeWord", packs=["WakeWord", "Audio"],
                  name="Wake word: train → INT8 ONNX → detect in recordings",
                  description="Train, export INT8 ONNX and run sliding-window detection on recorded clips.",
                  modality=["audio"], lifecycle=["train", "deploy", "infer"], tags=["wakeword", "int8", "detect"],
                  industries=["smart-home", "consumer-electronics"],
                  nodes=[ww_gen("ok_graphyn", "ok graphyn"), FEAT, TRAIN,
                         N("wakeword_export_onnx", {"quantize": True}, "export"), INGEST,
                         N("wakeword_infer", {"use_int8": True}, "detect")],
                  edges=[E(0, 1, "run", "run"), E(1, 2, "run", "run"), E(2, 3, "run", "run"),
                         E(4, 5, "output", "audio"), E(3, 5, "run", "model")]))
    B.append(base(slug="wakeword-detect", family="wakeword", pack="WakeWord", packs=["WakeWord", "Audio"],
                  name="Wake word: detect with a trained model",
                  description="Run a trained wake-word ONNX model over recordings and report detections per clip.",
                  modality=["audio"], lifecycle=["infer"], tags=["wakeword", "detect"],
                  industries=["smart-home", "qa"], status="needs-upstream",
                  requires=["tpl-wakeword-train-export (produces workspace/models/wakeword/hey_graphyn/hey_graphyn.onnx)"],
                  nodes=[INGEST, N("wakeword_infer", {"model_path": "workspace/models/wakeword/hey_graphyn/hey_graphyn.onnx"}, "detect")],
                  edges=[E(0, 1, "output", "audio")]))

    # ── Video ────────────────────────────────────────────────────────────────
    VIN = N("video_ingest", {"recursive": True}, "ingest")
    B.append(base(slug="video-scene-clips", family="video", pack="Video", packs=["Video"],
                  name="Video: quality gate → scene detection → clips",
                  description="Quality-gate videos, detect scene cuts and cut one clip per scene (ffmpeg), export clips + manifest.",
                  modality=["video"], lifecycle=["prep"], tags=["video", "scenes"],
                  industries=["media", "security", "sports"],
                  nodes=[VIN, N("video_quality_gate", {}, "quality"), N("scene_detect", {"threshold": 0.3}, "scenes"),
                         N("clip_segment", {"mode": "scenes"}, "clips"), N("video_exporter", {"clean": True}, "export")],
                  edges=[E(0, 1), E(1, 2), E(1, 3, "output", "video"), E(2, 3, "output", "scenes"), E(3, 4)]))
    B.append(base(slug="video-zero-shot-tagging", family="video", pack="Video", packs=["Video"],
                  name="Video: CLIP embeddings + zero-shot tags",
                  description="Sample frames, embed with CLIP and tag each video against zero-shot labels; export with annotations.",
                  modality=["video"], lifecycle=["label"], tags=["video", "clip", "zero-shot"],
                  industries=["media", "retail", "security"],
                  nodes=[VIN, N("video_embed", {"num_frames": 4, "zero_shot_labels": ["an animal", "a person", "a city street", "a cartoon"]}, "embed"),
                         N("video_exporter", {"clean": True}, "export")],
                  edges=[E(0, 1), E(0, 2, "output", "input"), E(1, 2, "output", "annotations")]))
    B.append(base(slug="video-action-recognition", family="video", pack="Video", packs=["Video"],
                  name="Video: action recognition (R3D-18 Kinetics-400)",
                  description="Classify actions with torchvision R3D-18 (Kinetics-400) and export videos with top-k action labels.",
                  modality=["video"], lifecycle=["infer"], tags=["video", "action"],
                  industries=["sports", "security", "fitness"],
                  nodes=[VIN, N("action_classify", {"arch": "r3d_18", "top_k": 3}, "classify"),
                         N("video_exporter", {"clean": True}, "export")],
                  edges=[E(0, 1), E(0, 2, "output", "input"), E(1, 2, "output", "annotations")]))
    B.append(base(slug="video-frame-captions-local-vlm", family="video", pack="Video", packs=["Video"],
                  name="Video: frame captions with a local VLM (Ollama moondream)",
                  description="Sample frames and caption them with a local vision-language model served by Ollama.",
                  modality=["video", "text"], lifecycle=["label"], tags=["video", "captions", "vlm"],
                  industries=["media", "accessibility"],
                  status="needs-endpoint",
                  requires=["Ollama reachable at OLLAMA_BASE_URL (host on GRAPHYN_HTTP_EGRESS_ALLOWLIST) with the 'moondream' model pulled"],
                  nodes=[VIN, N("frame_sample", {"mode": "uniform", "num_frames": 2}, "frames"),
                         N("video_caption", {"provider": "ollama", "model": "moondream", "frames_per_video": 2}, "caption"),
                         N("video_exporter", {"clean": True}, "export")],
                  edges=[E(0, 1), E(1, 2), E(0, 3, "output", "input"), E(2, 3, "captions", "annotations")]))
    B.append(base(slug="video-transcribe-captions", family="video", pack="Video", packs=["Video", "Common"],
                  name="Video: extract audio → ASR → captions",
                  description="Extract the audio track (ffmpeg), transcribe with local Whisper and export SRT/VTT captions.",
                  modality=["video", "audio", "text"], lifecycle=["infer"], tags=["video", "captions", "asr"],
                  industries=["media", "education", "accessibility"],
                  nodes=[VIN, N("av_align", {"method": "extract"}, "extract"), ASR,
                         N("caption_export", {"formats": ["srt", "vtt"]}, "captions")],
                  edges=[E(0, 1, "output", "video"), E(1, 2, "audio", "input"), E(2, 3)]))

    # ── Agents ───────────────────────────────────────────────────────────────
    LLM = {"provider": "ollama", "model": "qwen3:0.6b", "temperature": 0.0}
    B.append(base(slug="agents-local-llm-chat", family="agents", pack="Agents", packs=["Agents"],
                  name="Prompt template → local LLM chat (Ollama)",
                  description="Render a prompt template and answer with a local Ollama model (no API key).",
                  modality=["text"], lifecycle=["agent"], tags=["agents", "llm", "local"],
                  industries=["support", "general"],
                  status="needs-endpoint",
                  requires=["Ollama reachable at OLLAMA_BASE_URL (host on GRAPHYN_HTTP_EGRESS_ALLOWLIST) with the configured model pulled"],
                  nodes=[N("prompt_template", {"template": "In one sentence, what is a wake word?"}, "prompt"),
                         N("llm_chat", dict(LLM), "chat")],
                  edges=[E(0, 1, "output", "input")]))
    B.append(base(slug="agents-guarded-reply-memory", family="agents", pack="Agents", packs=["Agents"],
                  name="LLM reply → guardrail → approval → memory",
                  description="Draft a reply with a local LLM, block policy violations, pass an approval gate and persist to memory.",
                  modality=["text"], lifecycle=["agent", "govern"], tags=["agents", "guardrails", "hitl"],
                  industries=["support", "healthcare", "banking"],
                  status="needs-endpoint",
                  requires=["Ollama reachable at OLLAMA_BASE_URL (host on GRAPHYN_HTTP_EGRESS_ALLOWLIST) with the configured model pulled"],
                  nodes=[N("prompt_template", {"template": "Write a two-sentence status update for a customer whose order shipped."}, "prompt"),
                         N("llm_chat", dict(LLM), "chat"),
                         N("guardrail_filter", {"policies": ["pii", "secret"], "action": "block"}, "guard"),
                         N("hitl_approve", {"unattended_approve": True, "reason_required": False}, "approve"),
                         N("memory_store", {"namespace": "support-replies", "key": "last_reply"}, "remember")],
                  edges=[E(0, 1, "output", "input"), E(1, 2), E(2, 3), E(3, 4, "approved", "input")]))
    B.append(base(slug="agents-guardrail-approval-memory", family="agents", pack="Agents", packs=["Agents"],
                  name="Guardrail → approval gate → agent memory (no LLM)",
                  description="Screen a drafted message for PII/secrets, pass an approval gate (unattended in templates; "
                              "set unattended_approve=false for a human decision) and persist it to agent memory.",
                  modality=["text"], lifecycle=["agent", "govern"], tags=["agents", "guardrails", "hitl", "memory"],
                  industries=["support", "healthcare", "banking"],
                  nodes=[N("prompt_template", {"template": "Your order 1042 shipped today and arrives Friday."}, "draft"),
                         N("guardrail_filter", {"policies": ["pii", "secret"], "action": "block"}, "guard"),
                         N("hitl_approve", {"unattended_approve": True, "reason_required": False}, "approve"),
                         N("memory_store", {"namespace": "approved-messages", "key": "last_approved"}, "remember")],
                  edges=[E(0, 1), E(1, 2), E(2, 3, "approved", "input")]))
    B.append(base(slug="agents-tool-router-memory", family="agents", pack="Agents", packs=["Agents"],
                  name="Keyword tool router → agent memory",
                  description="Route a request to one of several named tools by keyword and log the routing decision to memory.",
                  modality=["text"], lifecycle=["agent"], tags=["agents", "tools", "memory"],
                  industries=["support", "devops"],
                  nodes=[N("prompt_template", {"template": "please check the run status of last night's job"}, "request"),
                         N("tool_router", {"tools": [{"name": "inspect_run", "keywords": ["run status", "status"]},
                                                     {"name": "list_pipelines", "keywords": ["list pipelines"]}],
                                           "strict": False}, "route"),
                         N("memory_store", {"namespace": "routing-log", "key": "last_route"}, "remember")],
                  edges=chain_edges(3)))
    B.append(base(slug="agents-structured-extract-validate", family="agents", pack="Agents", packs=["Agents", "Common"],
                  name="Structured extraction → JSON-schema validation",
                  description="Extract JSON fields from text (rule-based extractor, or an LLM provider when configured) and "
                              "validate them against a JSON schema.",
                  modality=["text"], lifecycle=["agent"], tags=["agents", "extraction", "schema"],
                  industries=["support", "sales", "legal"],
                  nodes=[N("prompt_template", {"template": "Customer Jane reports the invoice is wrong. Next step: refund by Friday."}, "text"),
                         N("structured_llm", {"provider": "rule_based", "schema_name": "ticket",
                                              "json_schema": {"type": "object", "properties": {"summary": {"type": "string"}}}}, "extract"),
                         N("output_schema_validate", {"json_schema": {"type": "object"}, "strict": False}, "validate")],
                  edges=chain_edges(3)))
    B.append(base(slug="agents-tool-router-mcp", family="agents", pack="Agents", packs=["Agents"],
                  name="Tool router → Graphyn MCP tool call",
                  description="Route a request to an allow-listed Graphyn MCP tool (read-only list_pipelines) and call it in-process.",
                  modality=["text"], lifecycle=["agent"], tags=["agents", "mcp", "tools"],
                  industries=["mlops", "devops"], status="needs-credentials",
                  requires=["credential of kind 'graphyn_mcp' (agent token) when platform auth is on"],
                  nodes=[N("prompt_template", {"template": "list pipelines"}, "request"),
                         N("tool_router", {"tools": [{"name": "list_pipelines", "keywords": ["list pipelines"]}], "strict": True}, "route"),
                         N("mcp_tool_call", {"tool_allowlist": ["list_pipelines"]}, "call")],
                  edges=chain_edges(3)))
    B.append(base(slug="agents-agent-loop", family="agents", pack="Agents", packs=["Agents"],
                  name="Agent loop (local LLM) with an empty tool belt",
                  description="Run a bounded ReAct-style agent loop on a local Ollama model and return its final answer.",
                  modality=["text"], lifecycle=["agent"], tags=["agents", "llm", "loop"],
                  industries=["support", "general"],
                  status="needs-endpoint",
                  requires=["Ollama reachable at OLLAMA_BASE_URL (host on GRAPHYN_HTTP_EGRESS_ALLOWLIST) with the configured model pulled"],
                  nodes=[N("prompt_template", {"template": "Give three tips for recording clean keyword audio."}, "goal"),
                         N("agent_loop", {"provider": "ollama", "model": "qwen3:0.6b", "max_steps": 2, "tool_allowlist": []}, "agent")],
                  edges=[E(0, 1, "output", "goal")]))
    B.append(base(slug="agents-email-alert", family="agents", pack="Agents", packs=["Agents", "Common"],
                  name="LLM summary → email alert (SMTP dry-run)",
                  description="Summarize an incident with a local LLM and email it (dry_run on until SMTP is configured).",
                  modality=["text"], lifecycle=["agent", "observe"], tags=["agents", "email"],
                  industries=["support", "devops"],
                  status="needs-endpoint",
                  requires=["Ollama reachable at OLLAMA_BASE_URL (host on GRAPHYN_HTTP_EGRESS_ALLOWLIST) with the configured model pulled"],
                  nodes=[N("prompt_template", {"template": "Summarize: nightly training finished, accuracy 0.91, 2 warnings."}, "prompt"),
                         N("llm_chat", dict(LLM), "summarize"),
                         N("send_email", {"to": "ops@example.com", "allowed_recipient_domains": ["example.com"],
                                          "subject": "Graphyn alert", "dry_run": True}, "email")],
                  edges=[E(0, 1, "output", "input"), E(1, 2)]))

    # ── Cross-pack ───────────────────────────────────────────────────────────
    B.append(base(slug="cross-call-analytics", family="cross", pack="Common", packs=["Audio", "Common"],
                  name="Call analytics: ASR → PII → structured fields → gate → store",
                  description="Transcribe calls locally, redact PII, extract summary/sentiment fields, gate and store results.",
                  modality=["audio", "text"], lifecycle=["infer", "govern"], tags=["captions", "call-analytics"],
                  industries=["callcenter", "banking", "insurance"],
                  nodes=[INGEST, COND, ASR, N("pii_redact", {"engine": "auto"}, "redact"),
                         N("structured_llm", {"provider": "rule_based", "schema_name": "call_analytics",
                                              "json_schema": {"type": "object", "properties": {"summary": {"type": "string"},
                                                                                               "sentiment": {"type": "string"}}}}, "extract"),
                         N("eval_gate", {"check_empty_transcript": False, "required_keys": []}, "gate"),
                         N("object_store", {"operation": "put", "prefix": "calls"}, "store")],
                  edges=[E(0, 1), E(1, 2), E(2, 3, "output", "transcript"), E(1, 3, "output", "audio"),
                         E(3, 4, "transcript", "input"), E(4, 5), E(5, 6)]))
    B.append(base(slug="cross-meeting-notes-memory", family="cross", pack="Agents", packs=["Audio", "Common", "Agents"],
                  name="Meeting notes: ASR → PII → extract → agent memory",
                  description="Transcribe, redact, extract action items and persist them to the agent memory store.",
                  modality=["audio", "text"], lifecycle=["infer", "agent"], tags=["captions", "meetings", "memory"],
                  industries=["sales", "consulting"],
                  nodes=[INGEST, ASR, N("pii_redact", {"engine": "regex"}, "redact"),
                         N("structured_llm", {"provider": "rule_based", "schema_name": "meeting",
                                              "json_schema": {"type": "object", "properties": {"next_step": {"type": "string"}}}}, "extract"),
                         N("memory_store", {"namespace": "meetings", "key": "last_meeting"}, "remember")],
                  edges=[E(0, 1), E(1, 2, "output", "transcript"), E(2, 3, "transcript", "input"), E(3, 4)]))
    B.append(base(slug="cross-tts-asr-roundtrip", family="cross", pack="Audio", packs=["Audio", "Common"],
                  name="TTS → ASR round-trip intelligibility check",
                  description="Synthesize a phrase, transcribe it back with local Whisper and export captions — a quick TTS QA loop.",
                  modality=["audio", "text"], lifecycle=["eval"], tags=["tts", "asr", "qa"],
                  industries=["ivr", "accessibility"],
                  nodes=[N("speech_synthesizer", {"backend": "mms", "text": "hello from graphyn"}, "synthesize"),
                         ASR, N("caption_export", {"formats": ["json"]}, "captions")],
                  edges=chain_edges(3)))
    B.append(base(slug="cross-video-audio-fusion", family="cross", pack="Video", packs=["Video", "Audio", "Common"],
                  name="Video + audio fusion embeddings",
                  description="Embed video frames with CLIP and the extracted audio with wav2vec2, then fuse per item.",
                  modality=["video", "audio"], lifecycle=["prep"], tags=["video", "fusion", "embeddings"],
                  industries=["media", "security"],
                  nodes=[VIN, N("av_align", {"method": "extract"}, "extract"),
                         N("embedding_generator", {"model": "wav2vec2"}, "audio_embed"),
                         N("video_embed", {"num_frames": 4}, "video_embed"),
                         N("multimodal_fusion", {"fusion_type": "concat", "output_dim": 256}, "fuse")],
                  edges=[E(0, 1, "output", "video"), E(1, 2, "audio", "input"), E(0, 3),
                         E(2, 4, "output", "audio"), E(3, 4, "output", "video")]))
    return B


INDUSTRY_LABEL = {
    "smart-home": "smart home", "callcenter": "contact center", "smart-city": "smart city",
    "consumer-electronics": "consumer electronics", "ivr": "IVR", "mlops": "MLOps", "qa": "QA",
}


def entry_for(b: dict, industry: str | None) -> dict:
    tid = f"tpl-{b['slug']}" + (f"-{industry}" if industry else "")
    label = INDUSTRY_LABEL.get(industry or "", (industry or "").replace("-", " "))
    name = b["name"] + (f" ({label})" if industry else "")
    desc = b["description"] + (f" Preset for {label}." if industry else "")
    tags = list(dict.fromkeys([b["family"], *b["tags"], *([industry] if industry else [])]))
    meta_extra: dict[str, Any] = {"base_template": f"tpl-{b['slug']}"}
    if b["requires"]:
        meta_extra["requires"] = list(b["requires"])
    return {
        "id": tid,
        "name": name,
        "description": desc,
        "pack": b["pack"],
        "packs_used": b["packs"],
        "industry": industry or "general",
        "modality": b["modality"],
        "lifecycle": b["lifecycle"],
        "tags": tags,
        "family": b["family"],
        "node_chain": deepcopy(b["nodes"]),
        "edges_hint": deepcopy(b["edges"]),
        "parameters": deepcopy(b["parameters"]),
        "mcp": {
            "instantiate": True,
            "required_tools": DEFAULT_TOOLS,
            "agent_brief": f"Instantiate {tid}, validate, save, execute, inspect outputs.",
        },
        "status": b["status"],
        "value_prop": b["description"].split(".")[0] + ".",
        "metadata_extra": meta_extra,
    }


def build_all() -> tuple[list[dict], list[dict]]:
    bases = build_bases()
    templates: list[dict] = []
    for b in bases:
        templates.append(entry_for(b, None))
        for ind in b["industries"]:
            templates.append(entry_for(b, ind))
    ids = [t["id"] for t in templates]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise SystemExit(f"duplicate template ids: {sorted(dupes)}")
    return bases, templates


def _full_registry():
    """Registry with every shipped PluginPackage plugin (venv installs mocked)."""
    import tempfile
    from unittest.mock import patch

    sys.path.insert(0, str(REPO))
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.venv_manager import PluginVenvManager

    tmp = tempfile.mkdtemp(prefix="tplcat_")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=tmp)
    mgr._plugins_dir = tmp
    with patch.object(PluginVenvManager, "ensure", return_value=Path("/tmp/fake-venv/bin/python")):
        for toml in sorted((REPO / "PluginPackage").rglob("plugin.toml")):
            if toml.parent.parent.name not in SHIPPED_PACKS:
                continue
            try:
                mgr.install(str(toml.parent) + "/")
            except Exception:
                continue
    return reg


def validate_templates(templates: list[dict], registry) -> dict[str, list[str]]:
    from app.core.execution.validation import validate_graph_ir
    from app.core.ir.loader import load_ir
    from app.core.templates.pipeline_template_materializer import materialize_template_entry

    failures: dict[str, list[str]] = {}
    for t in templates:
        try:
            graph = materialize_template_entry(t, registry=registry, ensure_seed_datasets=False)
            errs = [str(getattr(e, "message", e)) for e in validate_graph_ir(load_ir(graph), registry)]
        except Exception as exc:  # noqa: BLE001
            errs = [f"{type(exc).__name__}: {exc}"]
        if errs:
            failures[t["id"]] = errs
    return failures


def write_seed_graphs(bases: list[dict], templates: list[dict], registry, out_dir: Path) -> list[str]:
    """One runnable seed graph per base pipeline (stale seeds removed)."""
    from app.core.templates.pipeline_template_materializer import materialize_template_entry

    out_dir.mkdir(parents=True, exist_ok=True)
    by_id = {t["id"]: t for t in templates}
    wanted = {f"tpl-{b['slug']}" for b in bases}
    for stale in out_dir.glob("*.graph.json"):
        if stale.name[: -len(".graph.json")] not in wanted:
            stale.unlink()
    written = []
    for b in bases:
        tid = f"tpl-{b['slug']}"
        graph = materialize_template_entry(by_id[tid], registry=registry, ensure_seed_datasets=False)
        path = out_dir / f"{tid}.graph.json"
        path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(REPO)))
    return written


def merge_verification(templates: list[dict]) -> dict:
    if not VERIFICATION.is_file():
        return {}
    ver = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    runs = ver.get("runs") or {}
    for t in templates:
        r = runs.get(t["metadata_extra"]["base_template"])
        if r:
            t["metadata_extra"]["verified_run"] = {k: r.get(k) for k in ("run_id", "status", "verified_at", "note") if r.get(k)}
    return {k: v for k, v in ver.items() if k != "runs"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--seed-dir", type=Path, default=SEED_DIR)
    ap.add_argument("--no-seeds", action="store_true", help="do not (re)write seed graphs")
    ap.add_argument("--check", action="store_true", help="only validate; exit 1 on any invalid entry")
    ap.add_argument("--min", type=int, default=100, help="minimum number of catalog entries")
    args = ap.parse_args()

    bases, templates = build_all()
    registry = _full_registry()
    failures = validate_templates(templates, registry)
    for tid, errs in failures.items():
        print(f"INVALID {tid}: {errs[:3]}", file=sys.stderr)
    if args.check:
        print(f"{len(templates) - len(failures)}/{len(templates)} templates validate")
        return 1 if failures else 0
    if failures:
        print(f"ERROR: {len(failures)} templates do not validate — refusing to write the catalog", file=sys.stderr)
        return 1

    seed_paths = [] if args.no_seeds else write_seed_graphs(bases, templates, registry, args.seed_dir)
    ver_meta = merge_verification(templates)

    by_pack: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    by_family: dict[str, int] = defaultdict(int)
    used: set[str] = set()
    for t in templates:
        by_pack[t["pack"]] += 1
        by_status[t["status"]] += 1
        by_family[t["family"]] += 1
        used.update(s["node_type"] for s in t["node_chain"])
    shipped = set(registry._classes)
    doc = {
        "title": "Graphyn Pipeline Template Marketplace Catalog",
        "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/generate_pipeline_template_catalog.py",
        "shipped_packs": list(SHIPPED_PACKS),
        "removed_packs": list(REMOVED_PACKS),
        "total_templates": len(templates),
        "base_pipelines": len(bases),
        "counts_by_pack": dict(sorted(by_pack.items())),
        "counts_by_status": dict(sorted(by_status.items())),
        "counts_by_family": dict(sorted(by_family.items())),
        "coverage": {
            "node_types_shipped": len(shipped),
            "node_types_used_in_templates": len(used & shipped),
            "coverage_pct": round(100.0 * len(used & shipped) / max(1, len(shipped)), 2),
            "unused_node_types": sorted(shipped - used),
        },
        "verification": ver_meta,
        "seed_graphs": seed_paths,
        "templates": templates,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(templates)} templates ({len(bases)} base pipelines) -> {args.out}")
    print(f"Coverage: {doc['coverage']['coverage_pct']}% of shipped node types; unused: {doc['coverage']['unused_node_types']}")
    if len(templates) < args.min:
        print(f"ERROR: only {len(templates)} templates (min {args.min})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
