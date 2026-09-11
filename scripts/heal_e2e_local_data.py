#!/usr/bin/env python3
"""Heal workspace input trees for templates (host + Docker).

Creates *relative* symlinks from workspace/datasets/input -> examples/...
so the same links work on the host and inside the API container
(/app/workspace <-> /app/examples).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "workspace" / "datasets" / "input"
EX = ROOT / "examples"
WEBHOOK = "https://httpbin.org/post"


def rel_link(dst: Path, src: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        print(f"SKIP missing src: {src}")
        return
    target = Path(os_relpath(src, dst.parent))
    if dst.is_symlink() or dst.exists():
        if dst.is_symlink():
            try:
                if dst.resolve() == src.resolve():
                    return
            except FileNotFoundError:
                pass
            dst.unlink()
        elif dst.is_file():
            dst.unlink()
        else:
            # existing real dir ? leave alone
            print(f"KEEP existing dir: {dst}")
            return
    dst.symlink_to(target)
    print(f"link {dst} -> {target}")


def os_relpath(src: Path, start: Path) -> str:
    import os
    return os.path.relpath(str(src), str(start))


def heal_datasets() -> None:
    IN.mkdir(parents=True, exist_ok=True)

    # Top-level dataset packs (relative into examples)
    packs = {
        "wake-word": EX / "01_wake_word" / "data",
        "speech-commands": EX / "02_speech_commands" / "data",
        "environmental-sounds": EX / "03_environmental_sounds" / "data",
        "speaker-verification": EX / "04_speaker_verification" / "data",
        "speech-enhancement": EX / "05_speech_enhancement" / "data",
        "csv-data-processing": EX / "13_csv_data_processing" / "data",
        "doc-rag-ingest": EX / "25_doc_rag_ingest" / "data",
    }
    for name, src in packs.items():
        rel_link(IN / name, src)

    # Flat class labels many templates/ingest paths expect
    sc = EX / "02_speech_commands" / "data"
    for label in ("go", "yes", "no", "up", "down", "stop"):
        rel_link(IN / label, sc / label)

    env = EX / "03_environmental_sounds" / "data"
    # common alt names
    if (env / "dog").exists():
        rel_link(IN / "dog_bark", env / "dog")
    for label in ("car_horn", "siren", "rain", "footsteps", "background"):
        if (env / label).exists():
            rel_link(IN / label, env / label)

    se = EX / "05_speech_enhancement" / "data"
    if (se / "clean_speech").exists():
        rel_link(IN / "clean_speech", se / "clean_speech")
    elif se.exists():
        # sometimes wavs live directly under data
        pass

    print("dataset symlinks ok")


def patch_templates(td: Path) -> None:
    if not td.is_dir():
        print(f"no templates dir: {td}")
        return
    for path in sorted(td.glob("*.graph.json")):
        g = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for node in g.get("nodes") or []:
            t = node.get("node_type") or node.get("type")
            cfg = node.setdefault("config", {})
            if t == "asr_transcribe" and cfg.get("provider") in (
                "deepgram",
                "openai_compat",
                "assemblyai",
                None,
                "",
            ):
                cfg["provider"] = "local_whisper"
                cfg["model"] = cfg.get("model") or "tiny"
                cfg.setdefault("language", "en")
                changed = True
            if t == "structured_llm" and cfg.get("provider") in ("openai_compat", None, ""):
                cfg["provider"] = "local_heuristic"
                changed = True
            if t == "http_webhook":
                url = str(cfg.get("url") or "")
                if (not url) or ("example.com" in url):
                    cfg["url"] = WEBHOOK
                    changed = True
            if t == "stream_ingest" and "4fd1443e_nohash_0.wav" in str(cfg.get("file_path") or ""):
                cfg["file_path"] = "workspace/datasets/input/speech-commands/yes/yes_000.wav"
                # prefer any yes wav if renamed
                changed = True
        if changed:
            path.write_text(json.dumps(g, indent=2) + "\n", encoding="utf-8")
            print("patched", path.name)
    print(f"template free-path stamp done: {td}")


def main() -> None:
    heal_datasets()
    patch_templates(ROOT / "examples" / "templates")
    patch_templates(ROOT / "workspace" / "configs" / "templates")
    # sync workspace configs from examples if missing
    src = ROOT / "examples" / "templates"
    dst = ROOT / "workspace" / "configs" / "templates"
    dst.mkdir(parents=True, exist_ok=True)
    import shutil
    for p in src.glob("*.graph.json"):
        target = dst / p.name
        if not target.exists():
            shutil.copy2(p, target)
            print("copied", p.name)


if __name__ == "__main__":
    main()
