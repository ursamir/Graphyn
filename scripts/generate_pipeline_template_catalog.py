#!/usr/bin/env python3
"""Generate Graphyn pipeline template marketplace catalog (>=950 distinct entries)."""
from __future__ import annotations
import argparse, json, sys
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = REPO / "docs" / "PLUGIN_NODE_PLATFORM_CATALOG.json"
DEFAULT_REFINEMENTS = REPO / "docs" / "PLUGIN_NODE_REFINEMENTS.json"
DEFAULT_OUT = REPO / "docs" / "PIPELINE_TEMPLATE_CATALOG.json"
SEED_DIR = REPO / "examples" / "templates" / "marketplace"

def slug(*parts: str) -> str:
    raw = "-".join(p.strip().lower().replace("_", "-").replace(" ", "-") for p in parts if p)
    while "--" in raw:
        raw = raw.replace("--", "-")
    return raw.strip("-")

def chain(*node_types: str, overrides: list | None = None) -> list[dict]:
    out = []
    for i, nt in enumerate(node_types):
        item: dict[str, Any] = {"node_type": nt}
        if overrides and i < len(overrides) and overrides[i]:
            item["config_overrides"] = overrides[i]
        out.append(item)
    return out

def linear_edges(n: int) -> list[dict]:
    return [{"src_id": f"n{i}", "src_port": "output", "dst_id": f"n{i+1}", "dst_port": "input"} for i in range(n - 1)]

def tpl(*, family, name, description, pack, packs_used, industry, modality, lifecycle, tags,
        node_chain, parameters=None, status="proposed", value_prop="", edges_hint=None,
        required_tools=None, agent_brief="", honesty=None) -> dict:
    tid = slug("tpl", family, name)
    meta_extra = {}
    if honesty:
        meta_extra["honesty_banner"] = honesty
    return {
        "id": tid,
        "name": name.replace("-", " ").title(),
        "description": description,
        "pack": pack,
        "packs_used": packs_used,
        "industry": industry,
        "modality": modality,
        "lifecycle": lifecycle,
        "tags": tags,
        "family": family,
        "node_chain": node_chain,
        "edges_hint": edges_hint or [],
        "parameters": parameters or {},
        "mcp": {
            "instantiate": True,
            "required_tools": required_tools or [
                "search_templates", "get_template", "materialize_template",
                "validate_graph", "save_pipeline", "execute_pipeline",
            ],
            "agent_brief": agent_brief or f"Instantiate {tid}, validate, save, execute, inspect.",
        },
        "status": status,
        "value_prop": value_prop or f"Proves {pack} pack in {industry} {family} pipeline.",
        "metadata_extra": meta_extra,
    }

AUDIO_DOMAINS = ["smart-home","automotive","industrial","healthcare","callcenter","media","security","retail"]
AUDIO_TASKS = {
  "kws": ["dataset_ingest","audio_conditioner","segmenter","augmentation_pipeline","feature_frontend","dataset_builder","model_builder","trainer","evaluator"],
  "sed": ["dataset_ingest","audio_conditioner","audio_quality_gate","augmentation_pipeline","feature_frontend","audio_event_detector","evaluator"],
  "enhancement": ["dataset_ingest","audio_conditioner","speech_enhancer","audio_quality_gate","audio_exporter"],
  "diarization": ["dataset_ingest","audio_conditioner","speaker_separator","alignment_node","caption_export"],
  "captions": ["dataset_ingest","audio_conditioner","asr_transcribe","pii_redact","caption_export"],
  "call-analytics": ["dataset_ingest","audio_conditioner","asr_transcribe","pii_redact","structured_llm","http_webhook"],
  "podcast-level": ["dataset_ingest","audio_conditioner","speech_enhancer","audio_exporter"],
  "meeting-crm": ["dataset_ingest","audio_conditioner","speaker_separator","asr_transcribe","structured_llm","http_webhook"],
  "compliance": ["schedule_trigger","dataset_ingest","asr_transcribe","pii_redact","eval_gate","http_webhook"],
  "speaker-verify": ["dataset_ingest","audio_conditioner","segmenter","embedding_generator","dataset_builder","evaluator"],
  "edge-kws": ["dataset_ingest","audio_conditioner","feature_frontend","dataset_builder","model_builder","trainer","evaluator","edge_optimizer","deployment_packager"],
  "stream-sed": ["stream_ingest","stream_processor","feature_frontend","audio_event_detector","http_webhook"],
}
WAKE_PHRASES = [("en-hey-graphyn","en","hey graphyn"),("en-ok-home","en","ok home"),("es-hola-casa","es","hola casa"),
 ("de-hallo-haus","de","hallo haus"),("fr-bonjour-maison","fr","bonjour maison"),("hi-namaste","hi","namaste"),
 ("ja-sumimasen","ja","sumimasen"),("pt-ola-casa","pt","ola casa"),("ko-annyeong","ko","annyeong"),("zh-nihao","zh","ni hao")]
WAKE_STAGES = {
  "data-gen": ["wakeword_data_gen","dataset_versioner"],
  "feature": ["wakeword_data_gen","wakeword_feature_extract","dataset_builder"],
  "train": ["wakeword_feature_extract","wakeword_train","evaluator","experiment_tracker"],
  "export-onnx": ["wakeword_train","wakeword_export_onnx","artifact_checksum"],
  "infer": ["stream_ingest","wakeword_infer","http_webhook"],
  "e2e": ["wakeword_data_gen","wakeword_feature_extract","wakeword_train","wakeword_export_onnx","wakeword_infer"],
}
MCU = ["cortex-m4","cortex-m7","cortex-m33","cortex-m55-ethosu"]
TINY_TASKS = {
  "kws": (["mcu_dataset_ingest","mcu_label_taxonomy","mcu_window","mcu_mfcc","mcu_train"], ["audio"]),
  "anomaly-imu": (["mcu_dataset_ingest","mcu_label_taxonomy","mcu_window","mcu_feature_pipeline","mcu_train"], ["imu"]),
  "vision-tiny": (["mcu_dataset_ingest","mcu_label_taxonomy","mcu_feature_pipeline","mcu_model_zoo","mcu_train"], ["vision"]),
  "audio-event": (["mcu_dataset_ingest","mcu_window","mcu_spectrogram","mcu_train"], ["audio"]),
  "micro-speech": (["mcu_dataset_ingest","micro_speech_pipeline","tflm_host_sim","cmsis_pack_exporter"], ["audio"]),
}
TINY_IND = ["wearable","appliance","factory","agriculture","automotive","consumer-iot"]
EXPORTS = {
  "tflm": ["tinyml_ptq_calib_builder","tflm_quantize","tflm_convert","tflm_op_support_check","mcu_arena_estimator","cmsis_pack_exporter","tflm_host_sim"],
  "executorch": ["executorch_export","mcu_arena_estimator","mcu_glue_stubs"],
  "cmsis-pack": ["tflm_convert","cmsis_nn_optimize_flag","cmsis_pack_exporter","mcu_glue_stubs"],
  "vela": ["tflm_quantize","ethos_u_vela_compile","cmsis_pack_exporter"],
}
VIND = ["retail-shelf","traffic","pcb","weld","pallet","safety-gear","agriculture","medical-triage","sports","robotics","construction","logistics"]
VTASK = [("detect","yolo_task_detect"),("segment","yolo_task_segment"),("pose","yolo_task_pose"),("obb","yolo_task_obb_classify"),("classify","yolo_task_obb_classify")]
YFMT = ["onnx","engine","openvino","tflite","coreml","ncnn","rknn"]
RSRC = [("fs","rag_fs_connector"),("url","rag_url_crawl"),("notion","rag_notion_connector"),("slack","rag_slack_connector"),("pdf","rag_fs_connector")]
RSTORE = ["faiss","chroma","pgvector"]
RDOM = ["support","legal","eng-docs","ehr-lite","code","hr","sales"]
RCHUNK = [("recursive","chunk_recursive"),("semantic","chunk_semantic"),("markdown","chunk_markdown"),("hierarchical","chunk_hierarchical")]
VDOM = ["security","sports","factory","retail","media","traffic","warehouse"]
ASCEN = {
  "run-pipeline": ["prompt_template","llm_chat","tool_router","mcp_tool_call","output_schema_validate"],
  "ship-promote": ["prompt_template","guardrail_filter","tool_router","mcp_tool_call","hitl_approve","output_schema_validate"],
  "schedule-nightly": ["schedule_trigger","tool_router","mcp_tool_call","http_webhook"],
  "webhook-alert": ["guardrail_filter","llm_chat","http_webhook"],
  "hitl-approve": ["agent_loop","hitl_approve","mcp_tool_call","guardrail_filter"],
  "tool-router-mcp": ["tool_router","mcp_tool_call","memory_store","llm_chat"],
  "memory-chat": ["prompt_template","memory_store","llm_chat","guardrail_filter"],
  "schema-extract": ["prompt_template","llm_chat","output_schema_validate","structured_llm"],
}
MLOPS_PACKS = ["audio","vision","tinyml","rag","wakeword","video"]

def load_node_types(catalog_path: Path, refinements_path: Path) -> set[str]:
    nodes: set[str] = set()
    if catalog_path.is_file():
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        for n in data.get("nodes", []):
            nodes.add(n["node_type"])
    if refinements_path.is_file():
        ref = json.loads(refinements_path.read_text(encoding="utf-8"))
        for n in ref.get("added_nodes", []):
            nodes.add(n["node_type"])
    return nodes

def build_all() -> list[dict]:
    templates: list[dict] = []
    seen: set[str] = set()
    def add(t: dict) -> None:
        if t["id"] in seen or not t.get("node_chain"):
            return
        seen.add(t["id"]); templates.append(t)

    # Audio
    for task, nodes in AUDIO_TASKS.items():
        for dom in AUDIO_DOMAINS:
            packs = ["Audio"] + (["Common"] if any(x in nodes for x in ("trainer","structured_llm","http_webhook","edge_optimizer","embedding_generator","schedule_trigger")) else [])
            life = ["prep","train","eval"] if "trainer" in nodes else (["observe"] if "stream" in task or "compliance" in task else ["prep"])
            add(tpl(family="audio", name=f"{task}-{dom}", description=f"Audio {task} pipeline for {dom} industry use case.",
                    pack="Audio", packs_used=packs, industry=dom, modality=["audio"], lifecycle=life,
                    tags=["audio", task, dom], node_chain=chain(*nodes),
                    parameters={"dataset_path": f"workspace/datasets/input/{dom}-{task}", "sample_rate": 16000}))
            if "trainer" in nodes:
                add(tpl(family="audio", name=f"{task}-{dom}-edge-tflite", description=f"Edge TFLite deploy after audio {task} for {dom}.",
                        pack="Audio", packs_used=["Audio","Common"], industry=dom, modality=["audio"], lifecycle=["train","deploy"],
                        tags=["audio","edge","tflite",task],
                        node_chain=chain("dataset_ingest","audio_conditioner","feature_frontend","dataset_builder","model_builder","trainer","evaluator","edge_optimizer","deployment_packager",
                                         overrides=[None,None,None,None,None,None,None,{"backend":"tflite","quantization":"int8"},{"target":"edge"}]),
                        parameters={"export_format":"tflite"}, status="alter-existing"))
    for dom in AUDIO_DOMAINS:
        for name, nodes, tags in [
            (f"prep-augment-export-{dom}", ["dataset_ingest","audio_conditioner","audio_quality_gate","segmenter","augmentation_pipeline","audio_exporter"], ["prep","augment"]),
            (f"sim-rir-{dom}", ["dataset_ingest","environment_simulator","augmentation_pipeline","audio_exporter"], ["simulation","rir"]),
            (f"tts-voicebank-{dom}", ["speech_synthesizer","voice_converter","audio_quality_gate","audio_exporter"], ["tts","synth"]),
            (f"musicgen-bed-{dom}", ["audio_generator","audio_conditioner","audio_exporter"], ["generation"]),
            (f"annotator-taxonomy-{dom}", ["dataset_ingest","audio_annotator","audio_quality_gate","audio_exporter"], ["annotator"]),
        ]:
            add(tpl(family="audio", name=name, description=f"Audio prep variant {name}.", pack="Audio", packs_used=["Audio"],
                    industry=dom, modality=["audio"], lifecycle=["prep"], tags=["audio"]+tags, node_chain=chain(*nodes)))

    # WakeWord
    for pid, lang, phrase in WAKE_PHRASES:
        for stage, nodes in WAKE_STAGES.items():
            life = {"data-gen":["prep"],"feature":["prep"],"train":["train","eval"],"export-onnx":["deploy"],"infer":["observe"],"e2e":["prep","train","deploy","observe"]}[stage]
            add(tpl(family="wakeword", name=f"{pid}-{stage}", description=f"Wake-word '{phrase}' ({lang}) {stage} stage.",
                    pack="WakeWord", packs_used=["WakeWord","Audio","Common"], industry="consumer-iot", modality=["audio"],
                    lifecycle=life, tags=["wakeword",lang,stage], node_chain=chain(*nodes),
                    parameters={"phrase":phrase,"language":lang}))
            if stage == "export-onnx":
                for target in ("cpu","edge-tflite","mobile"):
                    add(tpl(family="wakeword", name=f"{pid}-deploy-{target}", description=f"Deploy wake-word '{phrase}' to {target}.",
                            pack="WakeWord", packs_used=["WakeWord","Common"], industry="consumer-iot", modality=["audio"],
                            lifecycle=["deploy"], tags=["wakeword","deploy",target],
                            node_chain=chain("wakeword_export_onnx","edge_optimizer","deployment_packager","artifact_checksum",
                                             overrides=[None,{"backend":"tflite" if "tflite" in target else "onnx"},{"target":"mobile" if target=="mobile" else "edge"},None]),
                            parameters={"phrase":phrase,"deploy_target":target}))

    # TinyML
    for task, (base, modality) in TINY_TASKS.items():
        for mcu in MCU:
            for ind in TINY_IND:
                for quant in ("ptq","qat"):
                    for ex, tail in EXPORTS.items():
                        if ex == "vela" and "ethosu" not in mcu:
                            continue
                        nodes = list(base) + [n for n in tail if n not in base]
                        if "mcu_dataset_health" not in nodes:
                            nodes.insert(min(2,len(nodes)), "mcu_dataset_health")
                        add(tpl(family="tinyml", name=f"{task}-{ind}-{mcu}-{quant}-{ex}",
                                description=f"TinyML {task} for {ind} on {mcu}, {quant.upper()} then {ex} export.",
                                pack="TinyML", packs_used=["TinyML","Common"], industry=ind, modality=modality,
                                lifecycle=["prep","train","eval","deploy"], tags=["tinyml",task,mcu,quant,ex],
                                node_chain=chain(*nodes),
                                parameters={"target_mcu":mcu,"quant_mode":quant,"export_format":ex,
                                            "arena_bytes_budget": 256000 if "m4" in mcu else 512000}))
                add(tpl(family="tinyml", name=f"{task}-{ind}-{mcu}-flash-ota",
                        description=f"Post-export MCU flash/OTA for {task} on {mcu} ({ind}). Honest needs-API.",
                        pack="TinyML", packs_used=["TinyML","MLOps"], industry=ind, modality=modality,
                        lifecycle=["deploy"], tags=["tinyml","flash","needs-api"],
                        node_chain=chain("cmsis_pack_exporter","artifact_checksum","mcu_ondevice_metrics","mcu_flash_ota"),
                        parameters={"target_mcu":mcu,"ota_channel":"staging"}, status="needs-api",
                        honesty="MCU flash/OTA and on-device metrics require Devices APIs not yet available. Do not fake device control."))
    for ind in TINY_IND:
        add(tpl(family="tinyml", name=f"feature-atoms-mfcc-{ind}", description=f"MCU window->MFCC feature atoms for {ind}.",
                pack="TinyML", packs_used=["TinyML"], industry=ind, modality=["audio"], lifecycle=["prep"],
                tags=["tinyml","features","mfcc"],
                node_chain=chain("mcu_dataset_ingest","mcu_window","mcu_mfcc","tinyml_ptq_calib_builder","dataset_versioner")))
        add(tpl(family="tinyml", name=f"feature-atoms-spec-{ind}", description=f"MCU window->spectrogram atoms for {ind}.",
                pack="TinyML", packs_used=["TinyML"], industry=ind, modality=["audio"], lifecycle=["prep"],
                tags=["tinyml","features","spectrogram"],
                node_chain=chain("mcu_dataset_ingest","mcu_window","mcu_spectrogram","dataset_versioner")))

    # Vision
    for task, task_node in VTASK:
        for ind in VIND:
            honesty = "Generic document/image triage only. No clinical diagnosis claims." if ind == "medical-triage" else None
            add(tpl(family="vision", name=f"yolo-{task}-train-{ind}", description=f"YOLO {task} training for {ind}, with yaml build + val.",
                    pack="Vision", packs_used=["Vision","Common"], industry=ind, modality=["vision"],
                    lifecycle=["prep","train","eval"], tags=["vision","yolo",task,"train"],
                    node_chain=chain("vision_dataset_ingest","vision_label_convert","vision_dataset_health","vision_train_val_split",
                                     "yolo_dataset_yaml_build","vision_augment",task_node,"yolo_train","yolo_val","experiment_tracker"),
                    parameters={"task":task,"imgsz":640,"epochs":100}, honesty=honesty))
            add(tpl(family="vision", name=f"yolo-{task}-hparam-{ind}", description=f"YOLO hyperparam search for {task} in {ind}.",
                    pack="Vision", packs_used=["Vision","MLOps"], industry=ind, modality=["vision"],
                    lifecycle=["train","eval"], tags=["vision","hparam",task],
                    node_chain=chain("vision_dataset_ingest","yolo_dataset_yaml_build","yolo_hyperparam_search","yolo_train","yolo_val","experiment_tracker"),
                    parameters={"n_trials":20,"task":task}, honesty=honesty))
            add(tpl(family="vision", name=f"yolo-{task}-resume-{ind}", description=f"Resume YOLO {task} training for {ind}.",
                    pack="Vision", packs_used=["Vision"], industry=ind, modality=["vision"], lifecycle=["train"],
                    tags=["vision","resume",task], node_chain=chain("yolo_resume_train","yolo_val","experiment_tracker"),
                    parameters={"resume_checkpoint":"workspace/artifacts/yolo/last.pt"}))
            add(tpl(family="vision", name=f"yolo-{task}-infer-{ind}", description=f"YOLO {task} batch infer + NMS for {ind}.",
                    pack="Vision", packs_used=["Vision"], industry=ind, modality=["vision"], lifecycle=["observe"],
                    tags=["vision","infer",task],
                    node_chain=chain("vision_dataset_ingest","yolo_predict","yolo_nms_postprocess","annotation_export_coco")))
            add(tpl(family="vision", name=f"yolo-{task}-hardneg-{ind}", description=f"Hard-negative mining for YOLO {task} in {ind}.",
                    pack="Vision", packs_used=["Vision","MLOps"], industry=ind, modality=["vision"],
                    lifecycle=["eval","prep"], tags=["vision","hardneg"],
                    node_chain=chain("vision_dataset_ingest","yolo_predict","vision_hard_negative_mine","dataset_diff","dataset_versioner")))
            if task in ("detect","pose"):
                add(tpl(family="vision", name=f"yolo-{task}-track-{ind}", description=f"ByteTrack-style tracking for YOLO {task} in {ind}.",
                        pack="Vision", packs_used=["Vision","Video"], industry=ind, modality=["vision","video"],
                        lifecycle=["observe"], tags=["vision","track"],
                        node_chain=chain("video_ingest","frame_sample","yolo_predict","yolo_track","video_exporter")))
            fmts = YFMT if task == "detect" else ["onnx","tflite","openvino","engine"]
            for fmt in fmts:
                add(tpl(family="vision", name=f"yolo-{task}-export-{fmt}-{ind}", description=f"Export YOLO {task} to {fmt} for {ind}.",
                        pack="Vision", packs_used=["Vision","Common"], industry=ind, modality=["vision"],
                        lifecycle=["deploy"], tags=["vision","export",fmt,task],
                        node_chain=chain("yolo_train","yolo_val","yolo_export","artifact_checksum","deployment_packager",
                                         overrides=[None,None,{"format":fmt},None,{"target":"edge"}]),
                        parameters={"export_format":fmt,"task":task}))
            if task in ("detect","segment"):
                for backend, node in (("onnx","onnx_runtime_infer"),("tensorrt","tensorrt_infer")):
                    add(tpl(family="vision", name=f"yolo-{task}-{backend}-infer-{ind}", description=f"{backend} runtime infer for YOLO {task} in {ind}.",
                            pack="Vision", packs_used=["Vision"], industry=ind, modality=["vision"], lifecycle=["observe"],
                            tags=["vision",backend,"infer"],
                            node_chain=chain("vision_dataset_ingest",node,"yolo_nms_postprocess","annotation_export_yolo")))
    for ind in VIND:
        add(tpl(family="vision", name=f"annotate-export-coco-{ind}", description=f"Export COCO annotations for {ind}.",
                pack="Vision", packs_used=["Vision"], industry=ind, modality=["vision"], lifecycle=["prep"],
                tags=["vision","coco"], node_chain=chain("vision_dataset_ingest","vision_label_convert","annotation_export_coco")))
        add(tpl(family="vision", name=f"annotate-export-yolo-{ind}", description=f"Export YOLO labels + data.yaml for {ind}.",
                pack="Vision", packs_used=["Vision"], industry=ind, modality=["vision"], lifecycle=["prep"],
                tags=["vision","yolo","yaml"],
                node_chain=chain("vision_dataset_ingest","vision_label_convert","yolo_dataset_yaml_build","annotation_export_yolo")))

    # RAG — ingest: all chunkers; query variants without full cartesian
    for src, src_node in RSRC:
        for store in RSTORE:
            for dom in RDOM:
                honesty = "Generic document Q&A scaffold only. No clinical decision support." if dom == "ehr-lite" else None
                for cid, cnode in RCHUNK:
                    add(tpl(family="rag", name=f"ingest-{src}-{cid}-{store}-{dom}",
                            description=f"RAG ingest from {src} using {cid} chunking into {store} for {dom}.",
                            pack="RAG", packs_used=["RAG","Common"], industry=dom, modality=["text"],
                            lifecycle=["ingest","prep"], tags=["rag","ingest",store,cid,src],
                            node_chain=chain(src_node,cnode,"text_embed","vector_store_write","eval_gate",
                                             overrides=[{"secret_name":f"{src}_token"} if src in ("notion","slack") else None, None, None, {"backend":store}, None]),
                            parameters={"vector_backend":store,"source":src,"chunker":cid}, honesty=honesty))
                add(tpl(family="rag", name=f"query-{src}-{store}-{dom}", description=f"Dense RAG query over {store} for {dom}.",
                        pack="RAG", packs_used=["RAG","Agents"], industry=dom, modality=["text"],
                        lifecycle=["observe","agent"], tags=["rag","query",store],
                        node_chain=chain("query_rewrite","vector_store_query","rag_rerank","contextual_compress","prompt_assemble","rag_generate","citation_attach",
                                         overrides=[None,{"backend":store},None,None,None,None,None]), honesty=honesty))
                add(tpl(family="rag", name=f"hybrid-{src}-{store}-{dom}", description=f"Hybrid BM25+dense retrieve for {dom} over {store}.",
                        pack="RAG", packs_used=["RAG"], industry=dom, modality=["text"], lifecycle=["observe"],
                        tags=["rag","hybrid","bm25"],
                        node_chain=chain("bm25_index_build","query_rewrite","hybrid_retrieve","rag_rerank","prompt_assemble","rag_generate","citation_attach"),
                        parameters={"vector_backend":store,"source":src}))
                add(tpl(family="rag", name=f"hyde-{store}-{dom}-{src}", description=f"HyDE generate then retrieve for {dom} ({store}).",
                        pack="RAG", packs_used=["RAG"], industry=dom, modality=["text"], lifecycle=["observe"],
                        tags=["rag","hyde"],
                        node_chain=chain("hyde_generate","text_embed","vector_store_query","rag_rerank","rag_generate","citation_attach")))
                add(tpl(family="rag", name=f"parent-doc-{store}-{dom}-{src}", description=f"Parent-document retriever for {dom} over {store}.",
                        pack="RAG", packs_used=["RAG"], industry=dom, modality=["text"], lifecycle=["observe"],
                        tags=["rag","parent-doc"],
                        node_chain=chain("chunk_hierarchical","text_embed","vector_store_write","parent_doc_retriever","prompt_assemble","rag_generate","citation_attach")))
        for dom in RDOM:
            add(tpl(family="rag", name=f"eval-{src}-{dom}", description=f"RAGAS-style eval for {dom} from {src}.",
                    pack="RAG", packs_used=["RAG","MLOps"], industry=dom, modality=["text"], lifecycle=["eval"],
                    tags=["rag","eval"], node_chain=chain("vector_store_query","rag_generate","rag_eval","eval_gate","experiment_tracker")))
            add(tpl(family="rag", name=f"kg-light-{src}-{dom}", description=f"Light KG extract + embed for {dom} from {src}.",
                    pack="RAG", packs_used=["RAG"], industry=dom, modality=["text"], lifecycle=["prep"],
                    tags=["rag","kg"], node_chain=chain(src_node,"chunk_recursive","kg_light_extract","text_embed","vector_store_write")))
            add(tpl(family="rag", name=f"multimodal-caption-{src}-{dom}", description=f"Caption then embed into RAG for {dom}.",
                    pack="RAG", packs_used=["RAG","Vision"], industry=dom, modality=["text","vision"],
                    lifecycle=["ingest","prep"], tags=["rag","multimodal"],
                    node_chain=chain(src_node,"multimodal_caption_embed","vector_store_write")))
    for dom in RDOM:
        honesty = "Generic document Q&A scaffold only. No clinical decision support." if dom == "ehr-lite" else None
        add(tpl(family="rag", name=f"agentic-rag-{dom}", description=f"Agentic RAG with tool_router, guardrails, citations for {dom}.",
                pack="RAG", packs_used=["RAG","Agents"], industry=dom, modality=["text"],
                lifecycle=["agent","observe"], tags=["rag","agentic"],
                node_chain=chain("guardrail_filter","query_rewrite","tool_router","hybrid_retrieve","rag_rerank","rag_generate","citation_attach","output_schema_validate","hitl_approve"),
                honesty=honesty))

    # Video
    for dom in VDOM:
        specs = [
            (f"ingest-scene-caption-{dom}", ["video_ingest","video_quality_gate","scene_detect","clip_segment","frame_sample","video_caption","video_exporter"], ["prep"], ["video"]),
            (f"action-classify-{dom}", ["video_ingest","clip_segment","action_classify","evaluator","http_webhook"], ["train","eval","observe"], ["video"]),
            (f"safety-monitor-{dom}", ["video_ingest","frame_sample","yolo_predict","action_classify","eval_gate","http_webhook"], ["observe"], ["video","vision"]),
            (f"video-rag-index-{dom}", ["video_ingest","scene_detect","clip_segment","video_caption","video_embed","text_embed","vector_store_write"], ["ingest","prep"], ["video","text"]),
            (f"embed-search-{dom}", ["video_ingest","clip_segment","video_embed","vector_store_write","vector_store_query"], ["prep","observe"], ["video"]),
        ]
        for name, nodes, life, mod in specs:
            packs = ["Video"]
            if "yolo_predict" in nodes: packs.append("Vision")
            if "vector_store_write" in nodes: packs.append("RAG")
            if "http_webhook" in nodes or "evaluator" in nodes: packs.append("Common")
            add(tpl(family="video", name=name, description=f"Video pipeline {name}.", pack="Video", packs_used=packs,
                    industry=dom, modality=mod, lifecycle=life, tags=["video",dom], node_chain=chain(*nodes)))
        add(tpl(family="video", name=f"av-align-asr-{dom}", description=f"Align video with audio ASR captions for {dom}.",
                pack="Video", packs_used=["Video","Audio"], industry=dom, modality=["video","audio"], lifecycle=["prep"],
                tags=["video","av","asr"],
                node_chain=chain("video_ingest","dataset_ingest","av_align","asr_transcribe","caption_export"),
                edges_hint=[
                    {"src_id":"n0","src_port":"output","dst_id":"n2","dst_port":"video"},
                    {"src_id":"n1","src_port":"output","dst_id":"n2","dst_port":"audio"},
                    {"src_id":"n2","src_port":"output","dst_id":"n3","dst_port":"input"},
                    {"src_id":"n3","src_port":"output","dst_id":"n4","dst_port":"input"},
                ]))

    # Agents
    for scen, nodes in ASCEN.items():
        for industry in ("mlops","support","security","compliance","retail","callcenter"):
            add(tpl(family="agents", name=f"{scen}-{industry}", description=f"Agents scenario {scen} for {industry} ops.",
                    pack="Agents", packs_used=["Agents","Common","MLOps"], industry=industry, modality=["text"],
                    lifecycle=["agent","observe"], tags=["agents",scen,industry], node_chain=chain(*nodes),
                    parameters={"approval_required": scen in ("ship-promote","hitl-approve")},
                    required_tools=["list_pipelines","execute_pipeline","secrets_list","propose_graph"],
                    agent_brief=f"Use Agents pack for {scen}; never embed raw secrets; HITL for promote."))

    # MLOps
    for pack in MLOPS_PACKS:
        add(tpl(family="mlops", name=f"train-eval-ship-{pack}", description=f"Train to eval_gate to model_card to ship for {pack}.",
                pack="MLOps", packs_used=["MLOps"], industry="mlops", modality=["text"], lifecycle=["train","eval","deploy"],
                tags=["mlops","ship",pack],
                node_chain=chain("run_metadata_stamp","evaluator","eval_gate","model_card","artifact_checksum","ship_package_create","ship_package_transition")))
        add(tpl(family="mlops", name=f"canary-promote-{pack}", description=f"Canary gate + ship promote for {pack}.",
                pack="MLOps", packs_used=["MLOps","Agents"], industry="mlops", modality=["text"], lifecycle=["deploy","observe"],
                tags=["mlops","canary",pack],
                node_chain=chain("ab_assign","canary_gate","hitl_approve","ship_package_promote","http_webhook"),
                parameters={"require_human_approval": True}))
        add(tpl(family="mlops", name=f"drift-watch-{pack}", description=f"Scheduled drift detect + dataset_diff for {pack}.",
                pack="MLOps", packs_used=["MLOps"], industry="mlops", modality=["text"], lifecycle=["observe"],
                tags=["mlops","drift",pack],
                node_chain=chain("schedule_trigger","feature_store_read","drift_detect","dataset_diff","eval_gate","http_webhook")))
        add(tpl(family="mlops", name=f"feature-store-loop-{pack}", description=f"Feature store write/read for {pack}.",
                pack="MLOps", packs_used=["MLOps"], industry="mlops", modality=["text"], lifecycle=["prep","observe"],
                tags=["mlops","feature-store",pack],
                node_chain=chain("feature_store_write","feature_store_read","artifact_checksum","run_metadata_stamp")))
        add(tpl(family="mlops", name=f"dataset-diff-version-{pack}", description=f"Diff dataset versions for {pack} retrains.",
                pack="MLOps", packs_used=["MLOps","Common"], industry="mlops", modality=["text"], lifecycle=["prep","eval"],
                tags=["mlops","dataset",pack],
                node_chain=chain("dataset_diff","dataset_versioner","dataset_balancer","run_metadata_stamp")))

    # Common utilities
    for industry in ("general","mlops","support","retail","security"):
        add(tpl(family="common", name=f"http-poll-transform-{industry}", description=f"HTTP to JSON transform to CSV for {industry}.",
                pack="Common", packs_used=["Common"], industry=industry, modality=["text"], lifecycle=["observe"],
                tags=["common","http"], node_chain=chain("http_request","json_transform","set_map","csv_table","object_store")))
        add(tpl(family="common", name=f"branch-merge-error-{industry}", description=f"If/switch with error_catch and merge for {industry}.",
                pack="Common", packs_used=["Common"], industry=industry, modality=["text"], lifecycle=["observe"],
                tags=["common","control-flow"],
                node_chain=chain("if_switch","python_code","error_catch","merge","wait_delay"),
                edges_hint=[
                    {"src_id":"n0","src_port":"true","dst_id":"n1","dst_port":"input"},
                    {"src_id":"n0","src_port":"false","dst_id":"n2","dst_port":"input"},
                    {"src_id":"n1","src_port":"output","dst_id":"n3","dst_port":"input_a"},
                    {"src_id":"n2","src_port":"output","dst_id":"n3","dst_port":"input_b"},
                    {"src_id":"n3","src_port":"output","dst_id":"n4","dst_port":"input"},
                ]))
        add(tpl(family="common", name=f"doc-chunk-store-{industry}", description=f"doc_parse_chunk bridge for {industry}.",
                pack="Common", packs_used=["Common"], industry=industry, modality=["text"], lifecycle=["ingest","prep"],
                tags=["common","docs","alter-existing"], node_chain=chain("doc_parse_chunk","eval_gate","object_store"), status="alter-existing"))
        add(tpl(family="common", name=f"embed-fusion-{industry}", description=f"Embedding + multimodal fusion for {industry}.",
                pack="Common", packs_used=["Common"], industry=industry, modality=["audio","vision","text"], lifecycle=["prep"],
                tags=["common","multimodal"], node_chain=chain("embedding_generator","multimodal_fusion","dataset_builder","dataset_balancer")))
        add(tpl(family="common", name=f"realtime-infer-{industry}", description=f"Realtime inference for {industry}.",
                pack="Common", packs_used=["Common"], industry=industry, modality=["audio"], lifecycle=["observe"],
                tags=["common","realtime"], node_chain=chain("stream_ingest","realtime_inference","http_webhook")))

    # Cross-pack
    cross = [
        ("meeting-audio-asr-rag", "Meeting audio to ASR to RAG", ["Audio","RAG"], "callcenter", ["audio","text"], ["prep","ingest","observe"],
         ["dataset_ingest","audio_conditioner","asr_transcribe","chunk_recursive","text_embed","vector_store_write","vector_store_query","rag_generate"]),
        ("camera-yolo-alert", "Camera YOLO detect to webhook", ["Vision","Common"], "security", ["vision"], ["observe"],
         ["vision_dataset_ingest","yolo_predict","yolo_nms_postprocess","eval_gate","http_webhook"]),
        ("tinyml-train-vela-flash", "TinyML train to Vela to needs-API flash", ["TinyML","MLOps"], "factory", ["audio"], ["train","deploy"],
         ["mcu_dataset_ingest","mcu_mfcc","mcu_train","tflm_quantize","ethos_u_vela_compile","cmsis_pack_exporter","mcu_flash_ota"]),
        ("video-av-rag", "Video scenes + ASR to multimodal RAG", ["Video","Audio","RAG"], "media", ["video","audio","text"], ["ingest","prep"],
         ["video_ingest","scene_detect","av_align","asr_transcribe","video_caption","text_embed","vector_store_write"]),
        ("retail-shelf-yolo-rag", "Shelf detect to RAG playbook", ["Vision","RAG"], "retail-shelf", ["vision","text"], ["observe","agent"],
         ["yolo_predict","multimodal_caption_embed","vector_store_query","rag_generate","http_webhook"]),
        ("wakeword-then-asr", "Wake-word gate then ASR extract", ["WakeWord","Audio","Common"], "smart-home", ["audio"], ["observe","agent"],
         ["stream_ingest","wakeword_infer","asr_transcribe","structured_llm","http_webhook"]),
        ("podcast-to-rag", "Podcast to ASR to RAG", ["Audio","RAG"], "media", ["audio","text"], ["prep","ingest"],
         ["dataset_ingest","audio_conditioner","asr_transcribe","chunk_semantic","text_embed","vector_store_write"]),
        ("factory-imu-drift-ship", "IMU TinyML to drift to ship", ["TinyML","MLOps"], "factory", ["imu"], ["observe","deploy"],
         ["mcu_dataset_ingest","mcu_feature_pipeline","drift_detect","model_card","ship_package_create"]),
        ("support-slack-rag-agent", "Slack to hybrid RAG agent", ["RAG","Agents"], "support", ["text"], ["ingest","agent"],
         ["rag_slack_connector","chunk_markdown","bm25_index_build","hybrid_retrieve","agent_loop","citation_attach","guardrail_filter"]),
        ("ppe-video-track-alert", "PPE detect+track to alert", ["Vision","Video","Common"], "safety-gear", ["vision","video"], ["observe"],
         ["video_ingest","frame_sample","yolo_predict","yolo_track","eval_gate","http_webhook"]),
    ]
    for name, desc, packs, industry, modality, lifecycle, nodes in cross:
        status = "needs-api" if "flash" in name else "proposed"
        honesty = "MCU flash/OTA requires Devices APIs not yet available." if status == "needs-api" else None
        add(tpl(family="cross", name=name, description=desc, pack=packs[0], packs_used=packs, industry=industry,
                modality=modality, lifecycle=lifecycle, tags=["cross-pack"]+[p.lower() for p in packs],
                node_chain=chain(*nodes), status=status, honesty=honesty,
                value_prop="Cross-pack composite proving packs compose as product surfaces."))
        for ind in ("retail","factory","healthcare","automotive","security","media","callcenter"):
            if ind == industry:
                continue
            add(tpl(family="cross", name=f"{name}-{ind}", description=f"{desc} — adapted for {ind}.",
                    pack=packs[0], packs_used=packs, industry=ind, modality=modality, lifecycle=lifecycle,
                    tags=["cross-pack", ind], node_chain=chain(*nodes), status=status, honesty=honesty))

    return templates

def coverage_report(templates: list[dict], node_types: set[str]) -> dict:
    used: set[str] = set()
    for t in templates:
        for step in t["node_chain"]:
            used.add(step["node_type"])
    orphans = sorted(node_types - used)
    pct = (100.0 * len(used & node_types) / len(node_types)) if node_types else 0.0
    return {
        "node_types_in_catalog": len(node_types),
        "node_types_used_in_templates": len(used & node_types),
        "coverage_pct": round(pct, 2),
        "orphans": orphans,
        "extra_nodes_in_templates_not_in_catalog": sorted(used - node_types),
    }

def materialize_graph(entry: dict) -> dict:
    nodes = []
    for i, step in enumerate(entry["node_chain"]):
        nodes.append({
            "id": f"n{i}",
            "node_type": step["node_type"],
            "config": deepcopy(step.get("config_overrides") or {}),
            "label": step.get("role") or step["node_type"],
            "capability_metadata": None,
            "event_trigger": None,
        })
    edges = entry.get("edges_hint") or linear_edges(len(nodes))
    meta = {
        "name": entry["id"], "seed": 42, "description": entry["description"], "created_at": None,
        "tags": entry.get("tags", []), "pack": entry.get("pack"), "industry": entry.get("industry"),
        "marketplace_id": entry["id"], "status": entry.get("status", "proposed"),
        "source_example": f"marketplace/{entry['id']}.graph.json",
    }
    if entry.get("metadata_extra"):
        meta.update(entry["metadata_extra"])
    return {"schema_version": "1.1", "metadata": meta, "nodes": nodes, "edges": edges, "parameters": entry.get("parameters") or {}}

def write_seed_graphs(templates: list[dict], out_dir: Path, n: int) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    by_family: dict[str, list] = defaultdict(list)
    for t in templates:
        by_family[t["family"]].append(t)
    picks: list[dict] = []
    while len(picks) < n and any(by_family.values()):
        for fam in list(by_family.keys()):
            if by_family[fam]:
                picks.append(by_family[fam].pop(0))
            if len(picks) >= n:
                break
            if not by_family[fam]:
                del by_family[fam]
    written = []
    for t in picks:
        path = out_dir / f"{t['id']}.graph.json"
        path.write_text(json.dumps(materialize_graph(t), indent=2) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(REPO)))
        if t["status"] == "proposed":
            t["status"] = "seeded"
    return written

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    ap.add_argument("--refinements", type=Path, default=DEFAULT_REFINEMENTS)
    ap.add_argument("--min", type=int, default=950)
    ap.add_argument("--seed-graphs", type=int, default=30)
    ap.add_argument("--seed-dir", type=Path, default=SEED_DIR)
    args = ap.parse_args()

    templates = build_all()
    refined_extra = {
        "yolo_dataset_yaml_build","yolo_hyperparam_search","yolo_resume_train",
        "bm25_index_build","parent_doc_retriever","hyde_generate",
        "mcu_window","mcu_mfcc","mcu_spectrogram","hitl_approve",
    }
    all_nodes = load_node_types(args.catalog, args.refinements) | refined_extra
    cov = coverage_report(templates, all_nodes)
    for orphan in list(cov["orphans"]):
        t = tpl(family="coverage", name=f"node-{orphan.replace('_','-')}",
                description=f"Coverage template ensuring node_type `{orphan}` appears in >=1 marketplace recipe.",
                pack="Common", packs_used=["Common"], industry="platform", modality=["text"], lifecycle=["observe"],
                tags=["coverage", orphan], node_chain=chain(orphan), value_prop=f"Coverage guarantee for {orphan}.")
        if t["id"] not in {x["id"] for x in templates}:
            templates.append(t)
    cov = coverage_report(templates, all_nodes)

    seed_paths = write_seed_graphs(templates, args.seed_dir, args.seed_graphs) if args.seed_graphs > 0 else []

    by_pack: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    by_family: dict[str, int] = defaultdict(int)
    for t in templates:
        by_pack[t["pack"]] += 1
        by_status[t["status"]] += 1
        by_family[t["family"]] += 1

    doc = {
        "title": "Graphyn Pipeline Template Marketplace Catalog",
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/generate_pipeline_template_catalog.py",
        "total_templates": len(templates),
        "counts_by_pack": dict(sorted(by_pack.items())),
        "counts_by_status": dict(sorted(by_status.items())),
        "counts_by_family": dict(sorted(by_family.items())),
        "coverage": cov,
        "seed_graphs": seed_paths,
        "templates": templates,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(templates)} templates -> {args.out}")
    print(f"Coverage: {cov['coverage_pct']}% ({cov['node_types_used_in_templates']}/{cov['node_types_in_catalog']})")
    if cov["orphans"]:
        print(f"ORPHANS ({len(cov['orphans'])}): {', '.join(cov['orphans'])}")
    if seed_paths:
        print(f"Seeded {len(seed_paths)} graphs under {args.seed_dir}")
    if len(templates) < args.min:
        print(f"ERROR: only {len(templates)} templates (min {args.min})", file=sys.stderr)
        return 1
    if cov["orphans"]:
        print("ERROR: orphan node_types remain", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
