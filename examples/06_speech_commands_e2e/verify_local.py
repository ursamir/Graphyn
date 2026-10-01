#!/usr/bin/env python3
"""Example 06 — in-process verification run against PluginPackage/ sources.

Chains the node classes directly (no plugin install, no API) with the exact
configs from this folder's *.graph.json: 6× preprocess → train → per-label
inference on the held-out test split. Writes <out_dir>/out/report.json.

Usage:
  GRAPHYN_SKIP_PLUGIN_LOAD=1 GRAPHYN_TF_DEVICE=cpu \
      venv/bin/python examples/06_speech_commands_e2e/verify_local.py <out_dir> [epochs]
"""
import json, os, sys, time, pathlib, collections
import numpy as np
REPO = pathlib.Path(__file__).resolve().parents[2]; sys.path.insert(0, str(REPO))
pathlib.Path(sys.argv[1]).mkdir(parents=True, exist_ok=True)
os.chdir(sys.argv[1])  # exporter refuses paths outside cwd
EPOCHS = int(sys.argv[2]) if len(sys.argv) > 2 else 50
from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry
reg = NodeRegistry(); disc = AutoDiscovery(reg)
for d in ["Audio/dataset_ingest","Audio/audio_conditioner","Audio/segmenter","Audio/audio_quality_gate","Audio/augmentation_pipeline","Audio/audio_exporter","Audio/feature_frontend","Common/dataset_builder","Common/trainer","Common/evaluator","Common/edge_optimizer","Common/realtime_inference"]:
    for e in ("types.py","nodes.py"):
        p = REPO/"PluginPackage"/d/e
        if p.is_file(): disc._process_module(disc._import_file(p, package_prefix=None))
EX = REPO/"examples/06_speech_commands_e2e"
DATA = REPO/"examples/02_speech_commands/data"
OUT = pathlib.Path("out"); OUT.mkdir(exist_ok=True)
report = {"phases": {}}
def run_graph(g, overrides, seed=42):
    vals = {}; timings = {}; counts = {}
    order = [n["id"] for n in g["nodes"]]
    nodes = {n["id"]: n for n in g["nodes"]}
    for nid in order:
        n = nodes[nid]; cfg = dict(n["config"]); cfg.update(overrides.get(n["node_type"], {})); cfg.update(overrides.get(nid, {}))
        cls = reg.get_class(n["node_type"]); node = cls(config=cfg, seed=seed)
        ins = {}
        for e in g["edges"]:
            if e["dst_id"] == nid: ins[e["dst_port"]] = vals[e["src_id"]][e["src_port"]]
        if hasattr(node, "setup"): node.setup()
        t0 = time.time(); out = node.process(ins); timings[nid] = round(time.time()-t0, 2)
        vals[nid] = out
        counts[nid] = {k: (len(v) if isinstance(v, list) else 1) for k, v in out.items()}
    return vals, timings, counts
# Phase 1
ds_root = "out/dataset/speech_commands"
for lbl in ["yes","no","up","down","go","stop"]:
    f = EX/("pipeline_preprocess.graph.json" if lbl=="yes" else f"pipeline_preprocess_{lbl}.graph.json")
    g = json.loads(f.read_text())
    _, t, c = run_graph(g, {"dataset_ingest": {"path": str(DATA/lbl)}, "audio_exporter": {"output_dir": ds_root}})
    report["phases"][f"pre_{lbl}"] = {"timings": t, "counts": c}
    print("pre", lbl, c, flush=True)
# Phase 2
g = json.loads((EX/"pipeline_train_ml.graph.json").read_text())
ov = {"dataset_ingest": {"path": str(pathlib.Path(ds_root, "v1").resolve())},
      "model_builder": {"output_path": "out/models"}, "trainer": {"output_path": "out/train", "epochs": EPOCHS, "device": "cpu"},
      "evaluator": {"output_path": "out/train"}, "edge_optimizer": {"output_path": "out/train/tflite"}}
vals, t, c = run_graph(g, ov)
ds = vals["dataset_builder_0"]["output"]
report["phases"]["train"] = {"timings": t, "counts": c, "X_train": list(ds.X_train.shape), "X_val": list(ds.X_val.shape), "X_test": list(ds.X_test.shape),
    "labels": ds.labels, "split_counts": ds.metadata.get("split_counts"), "epochs_run": len(vals["trainer_0"]["output"].history["loss"]),
    "best_val_acc": max(vals["trainer_0"]["output"].history["val_accuracy"]), "lr0": vals["trainer_0"]["output"].history.get("learning_rate", [None])[0],
    "metrics": {k: v for k, v in vals["evaluator_0"]["output"].metrics.items() if k in ("test_accuracy","roc_auc","per_class")},
    "tflite": vals["edge_optimizer_0"]["output"].model_dump(exclude={"metadata"})}
print("train", json.dumps(report["phases"]["train"], default=str)[:1500], flush=True)
# Inference on the test split (held out by source thanks to group_by_source)
gi = json.loads((EX/"pipeline_infer.graph.json").read_text())
model = str(pathlib.Path("out/train/tflite/model.tflite").resolve())
tot = 0; ok = 0; per = {}
for lbl in ds.labels:
    vals, t, c = run_graph(gi, {"dataset_ingest": {"path": str(pathlib.Path(ds_root, "v1", "test", lbl).resolve())}, "realtime_inference": {"model_path": model}})
    preds = vals["realtime_inference_0"]["output"]
    hit = sum(p.predicted_label == lbl for p in preds); per[lbl] = [hit, len(preds)]; tot += len(preds); ok += hit
report["phases"]["infer"] = {"per_label": per, "accuracy": ok / max(tot, 1), "n": tot}
print("infer", report["phases"]["infer"], flush=True)
# leakage check
m = json.load(open(pathlib.Path(ds_root, "v1", "metadata.json")))
gsplit = collections.defaultdict(set)
for e in m: gsplit[e["metadata"].get("parent") or e["path"]].add(e["split"])
report["leakage_sources_multi_split"] = sum(len(v) > 1 for v in gsplit.values())
json.dump(report, open("out/report.json", "w"), indent=1, default=str)
print("leak", report["leakage_sources_multi_split"])
