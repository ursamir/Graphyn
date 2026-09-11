#!/usr/bin/env python3
"""Create local dataset symlink trees expected by ex-* templates (gitignored workspace/)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "workspace" / "datasets" / "input"
WEBHOOK = "https://httpbin.org/post"


def link(dst: Path, src: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        if dst.is_symlink() and dst.resolve() == src.resolve():
            return
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        else:
            return
    dst.symlink_to(src)


def heal_datasets() -> None:
    # speech-commands class dirs
    sc = IN / "speech-commands"
    sc.mkdir(parents=True, exist_ok=True)
    for label in ("go", "yes", "no", "up", "down", "stop"):
        link(sc / label, IN / label)

    env = IN / "environmental-sounds"
    mapping = {
        "dog": "dog_bark",
        "car_horn": "car_horn",
        "siren": "siren",
        "rain": "rain",
        "footsteps": "footsteps",
        "background": "background",
    }
    for name, target in mapping.items():
        link(env / name, IN / target)

    sv = IN / "speaker-verification"
    for s in ("speaker_001", "speaker_002", "speaker_003", "speaker_004"):
        link(sv / s, IN / s)

    link(IN / "speech-enhancement" / "clean_speech", IN / "clean_speech")
    print("dataset symlinks ok")


def patch_workspace_templates() -> None:
    td = ROOT / "workspace" / "configs" / "templates"
    if not td.is_dir():
        print("no workspace templates dir")
        return
    for path in sorted(td.glob("*.graph.json")):
        g = json.loads(path.read_text())
        changed = False
        for node in g.get("nodes") or []:
            t = node.get("node_type") or node.get("type")
            cfg = node.setdefault("config", {})
            if t == "asr_transcribe" and cfg.get("provider") in ("deepgram", "openai_compat", "assemblyai"):
                cfg["provider"] = "local_whisper"
                cfg["model"] = "tiny"
                cfg.setdefault("language", "en")
                changed = True
            if t == "structured_llm" and cfg.get("provider") == "openai_compat":
                cfg["provider"] = "local_heuristic"
                changed = True
            if t == "http_webhook" and "example.com" in str(cfg.get("url") or ""):
                cfg["url"] = WEBHOOK
                changed = True
            if t == "stream_ingest" and "4fd1443e_nohash_0.wav" in str(cfg.get("file_path") or ""):
                cfg["file_path"] = "workspace/datasets/input/speech-commands/yes/yes_000.wav"
                changed = True
            if t == "model_builder" and not cfg.get("output_path"):
                cfg["output_path"] = "workspace/artifacts/speech-commands/models"
                changed = True
            if t == "dataset_ingest" and str(cfg.get("path") or "").endswith("speech-commands") and "limit" not in cfg:
                cfg["limit"] = 8
                changed = True
        if changed:
            path.write_text(json.dumps(g, indent=2) + "\n")
            print("patched", path.name)
    print("workspace template free-path stamp done")


def main() -> None:
    heal_datasets()
    patch_workspace_templates()


if __name__ == "__main__":
    main()
