# app/core/ir/legacy_aliases.py
"""
Bounded Context:  BC1 — Graph Language
Responsibility:   Migrate obsolete node_type names (pre-plugin rename) to the
                  current PluginPackage registry types, including config field
                  remaps and removal of retired ``split`` nodes (ratios fold
                  into ``audio_exporter``).
Owns:             migrate_legacy_node_types()
Public Surface:   migrate_legacy_node_types(data) -> dict
Must NOT:         Execute pipelines or touch the node registry.
Dependencies:     stdlib copy/typing only.
Reason To Change: Additional legacy aliases or config remaps are discovered.
"""
from __future__ import annotations

import copy
from typing import Any


# Simple 1:1 type renames (config remapped separately).
_TYPE_ALIASES: dict[str, str] = {
    "input": "dataset_ingest",
    "clean": "audio_conditioner",
    "normalize": "audio_conditioner",
    "denoise": "speech_enhancer",
    "fade": "audio_conditioner",
    "augment": "augmentation_pipeline",
    "segment": "segmenter",
    "silence_detector": "segmenter",
    "vad": "segmenter",
    "tag": "audio_annotator",
    "export": "audio_exporter",
}


def _remap_config(old_type: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Rewrite config keys for a legacy node type to the modern equivalent."""
    c = dict(cfg or {})

    if old_type == "input":
        return {
            "path": c.get("path", ""),
            "source_type": c.get("source_type", "filesystem"),
            "recursive": bool(c.get("recursive", False)),
        }

    if old_type == "clean":
        sr = c.get("target_sample_rate", c.get("sample_rate", 16000))
        return {
            "target_sample_rate": int(sr),
            "mono": bool(c.get("mono", True)),
        }

    if old_type == "normalize":
        method = str(c.get("method", "lufs")).lower()
        level = float(c.get("target_level", c.get("target_lufs", -23.0)))
        out = {
            "normalize": True,
            "normalize_method": method if method in ("peak", "rms", "lufs") else "lufs",
            "mono": True,
        }
        if out["normalize_method"] == "lufs":
            out["target_lufs"] = level
        else:
            out["target_level_db"] = level
        return out

    if old_type == "denoise":
        return {
            "backend": "spectral",
            "denoise": True,
            "dereverb": False,
        }

    if old_type == "fade":
        # No dedicated fade node — conditioner preserves audio with light trim off.
        return {
            "trim_silence": False,
            "normalize": False,
            "mono": True,
        }

    if old_type == "augment":
        gain = c.get("gain_db", [-6, 6])
        if not isinstance(gain, (list, tuple)) or len(gain) != 2:
            gain = [-6, 6]
        return {
            "copies_per_sample": int(c.get("copies_per_sample", 1)),
            "augmentations": [
                {
                    "type": "gain",
                    "apply_prob": 1.0,
                    "gain_db": [float(gain[0]), float(gain[1])],
                }
            ],
        }

    if old_type == "segment":
        return {
            "mode": "fixed",
            "window_ms": int(c.get("window_ms", 1000)),
            "overlap": float(c.get("overlap", 0.0)),
        }

    if old_type == "silence_detector":
        thr = c.get("threshold_db", c.get("silence_threshold_db", -40))
        # segmenter silence_threshold_db is positive dB below peak in some modes;
        # map absolute threshold conservatively.
        return {
            "mode": "silence",
            "silence_threshold_db": abs(float(thr)),
        }

    if old_type == "vad":
        return {
            "mode": "vad",
            "vad_aggressiveness": int(c.get("aggressiveness", c.get("vad_aggressiveness", 2))),
            "window_ms": int(c.get("frame_ms", c.get("window_ms", 30))) * 10
            if "frame_ms" in c
            else int(c.get("window_ms", 1000)),
        }

    if old_type == "tag":
        tags = c.get("tags", {})
        if isinstance(tags, str):
            try:
                import json

                tags = json.loads(tags)
            except Exception:
                tags = {"note": tags}
        return {
            "annotation_mode": "passthrough",
            "propagate_metadata": True,
            "taxonomy": tags if isinstance(tags, dict) else {},
        }

    if old_type == "export":
        output = c.get("output_dir") or c.get("output") or "workspace/datasets/output"
        project = c.get("project")
        if project and "output_dir" not in c:
            output = f"{str(output).rstrip('/')}/{project}"
        train = float(c.get("train", 0.7))
        val = float(c.get("val", 0.15))
        test = float(c.get("test", max(0.0, 1.0 - train - val)))
        # Prefer explicit split_ratios if present
        ratios = c.get("split_ratios")
        if not isinstance(ratios, dict):
            ratios = {"train": train, "val": val, "test": test}
        return {
            "output_dir": str(output),
            "version_tag": str(c.get("version_tag", c.get("version", "v1"))),
            "split_ratios": ratios,
            "random_seed": int(c.get("random_seed", c.get("seed", 42))),
            "append": bool(c.get("append", False)),
        }

    return c


def _fold_split_nodes(data: dict[str, Any]) -> dict[str, Any]:
    """Remove legacy ``split`` nodes; fold ratios into downstream exporters."""
    nodes = list(data.get("nodes") or [])
    edges = list(data.get("edges") or [])
    split_ids = {n["id"] for n in nodes if n.get("node_type") == "split"}
    if not split_ids:
        return data

    split_cfg = {
        n["id"]: n.get("config") or {}
        for n in nodes
        if n.get("node_type") == "split"
    }

    # Map split → exporter: edge split → export*
    split_to_export: dict[str, str] = {}
    for e in edges:
        if e.get("src_id") in split_ids:
            split_to_export[e["src_id"]] = e["dst_id"]

    by_id = {n["id"]: n for n in nodes}
    for sid, eid in split_to_export.items():
        exp = by_id.get(eid)
        if not exp:
            continue
        sc = split_cfg.get(sid, {})
        train = float(sc.get("train", 0.7))
        val = float(sc.get("val", 0.15))
        test = float(sc.get("test", max(0.0, 1.0 - train - val)))
        cfg = dict(exp.get("config") or {})
        cfg["split_ratios"] = {"train": train, "val": val, "test": test}
        # If still legacy export keys, remap now
        if exp.get("node_type") in ("export", "audio_exporter"):
            remapped = _remap_config("export", {**cfg, "train": train, "val": val, "test": test})
            exp["config"] = remapped
            exp["node_type"] = "audio_exporter"
        else:
            exp["config"] = cfg

    # Rewire: pred → split → succ becomes pred → succ
    new_edges: list[dict[str, Any]] = []
    incoming: dict[str, list[dict[str, Any]]] = {sid: [] for sid in split_ids}
    outgoing: dict[str, list[dict[str, Any]]] = {sid: [] for sid in split_ids}
    for e in edges:
        if e.get("dst_id") in split_ids:
            incoming[e["dst_id"]].append(e)
        elif e.get("src_id") in split_ids:
            outgoing[e["src_id"]].append(e)
        else:
            new_edges.append(e)

    for sid in split_ids:
        for ie in incoming.get(sid, []):
            for oe in outgoing.get(sid, []):
                new_edges.append(
                    {
                        "src_id": ie["src_id"],
                        "src_port": ie.get("src_port", "output"),
                        "dst_id": oe["dst_id"],
                        "dst_port": oe.get("dst_port", "input"),
                        "condition": oe.get("condition") or ie.get("condition"),
                    }
                )

    data = dict(data)
    data["nodes"] = [n for n in nodes if n.get("node_type") != "split"]
    data["edges"] = new_edges
    return data


def migrate_legacy_node_types(data: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied IR dict with legacy node types migrated.

    Safe to call on already-modern graphs (no-op for unknown/current types).
    """
    if not isinstance(data, dict):
        return data
    out = copy.deepcopy(data)
    out = _fold_split_nodes(out)

    nodes = out.get("nodes") or []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        old = node.get("node_type")
        if not isinstance(old, str) or old not in _TYPE_ALIASES:
            # Still remap export-shaped configs if already renamed somehow
            if old == "audio_exporter":
                cfg = node.get("config") or {}
                if "output" in cfg or "project" in cfg:
                    node["config"] = _remap_config("export", cfg)
            continue
        cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
        node["config"] = _remap_config(old, cfg)
        node["node_type"] = _TYPE_ALIASES[old]
        # Keep human label if missing
        if not node.get("label"):
            node["label"] = old

    out["nodes"] = nodes
    return out
