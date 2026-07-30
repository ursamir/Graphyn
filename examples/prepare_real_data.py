#!/usr/bin/env python3
"""
examples/prepare_real_data.py
==============================
Ensures Google Speech Commands v0.02 raw data is present, then copies real
audio into each example's own data/ directory.

Behavior:
1) Download official archives to workspace/datasets/raw/ if missing.
2) Extract into:
   - workspace/datasets/raw/speech_commands_train/
   - workspace/datasets/raw/speech_commands_test/
3) Populate examples/*/data from those extracted directories.

Usage:
    venv/bin/python examples/prepare_real_data.py

Data layout after running this script:
    examples/01_wake_word/data/
        wake_word/   ← yes/ from test set  (200 files)
        background/  ← no/ + _silence_/    (200 files)
        noise/       ← _background_noise_/ (6 real noise WAVs)

    examples/02_speech_commands/data/
        yes/, no/, up/, down/, go/, stop/  ← test set (200 files each)

    examples/03_environmental_sounds/data/
        dog/, cat/, bird/, happy/, house/  ← train set (200 files each)

    examples/04_speaker_verification/data/
        speaker_001/ … speaker_006/        ← train set, top speakers (15 utterances each)
        speaker_manifest.txt

    examples/05_speech_enhancement/data/
        clean_speech/  ← yes/ + no/ from test set (200 files)
        noise/         ← _background_noise_/ (6 real noise WAVs)
"""
from __future__ import annotations

import random
import shutil
import tarfile
import urllib.request
from collections import defaultdict
from pathlib import Path

TRAIN_DIR = Path("workspace/datasets/raw/speech_commands_train")
TEST_DIR  = Path("workspace/datasets/raw/speech_commands_test")
RAW_ROOT  = Path("workspace/datasets/raw")
EXAMPLES  = Path("examples")
TRAIN_ARCHIVE = RAW_ROOT / "speech_commands_v0.02.tar.gz"
TEST_ARCHIVE = RAW_ROOT / "speech_commands_test_set_v0.02.tar.gz"
TRAIN_URL = "https://storage.googleapis.com/download.tensorflow.org/data/speech_commands_v0.02.tar.gz"
TEST_URL = "https://storage.googleapis.com/download.tensorflow.org/data/speech_commands_test_set_v0.02.tar.gz"

SEED = 42
random.seed(SEED)


# ── Helpers ───────────────────────────────────────────────────────────────────

def copy_files(src_dir: Path, dst_dir: Path, limit: int | None = None,
               shuffle: bool = True) -> int:
    """Copy WAV files from src_dir to dst_dir, optionally limiting count."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(src_dir.glob("*.wav"))
    if shuffle:
        random.shuffle(files)
    if limit:
        files = files[:limit]
    for f in files:
        shutil.copy2(f, dst_dir / f.name)
    return len(files)


def clear_data_dir(path: Path) -> None:
    """Remove and recreate a data directory."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def check_prerequisites() -> bool:
    ok = True
    if not TRAIN_DIR.exists():
        print(f"  ✗ Missing: {TRAIN_DIR}")
        print("    Run: tar -xzf speech_commands_v0.02.tar.gz "
              "-C workspace/datasets/raw/ --transform 's|^\\./|speech_commands_train/|'")
        ok = False
    if not TEST_DIR.exists():
        print(f"  ✗ Missing: {TEST_DIR}")
        print("    Run: tar -xzf speech_commands_test_set_v0.02.tar.gz "
              "-C workspace/datasets/raw/ --transform 's|^\\./|speech_commands_test/|'")
        ok = False
    return ok


def _download_if_missing(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"  ✓ Archive present: {dest}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  ↓ Downloading: {url}")
    urllib.request.urlretrieve(url, str(dest))
    print(f"  ✓ Downloaded: {dest}")


def _extract_archive_if_needed(archive: Path, target_dir: Path, prefix: str) -> None:
    if target_dir.exists():
        print(f"  ✓ Extracted directory present: {target_dir}")
        return
    print(f"  ↓ Extracting: {archive.name} → {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode="r:gz") as tf:
        for member in tf.getmembers():
            member_name = member.name
            if member_name.startswith("./"):
                member_name = member_name[2:]
            if not member_name:
                continue
            member.name = f"{prefix}/{member_name}"
            tf.extract(member, path=str(RAW_ROOT))
    print(f"  ✓ Extracted: {target_dir}")


def ensure_raw_data() -> bool:
    """Ensure train/test archives and extracted directories are available."""
    try:
        _download_if_missing(TRAIN_URL, TRAIN_ARCHIVE)
        _download_if_missing(TEST_URL, TEST_ARCHIVE)
        _extract_archive_if_needed(TRAIN_ARCHIVE, TRAIN_DIR, "speech_commands_train")
        _extract_archive_if_needed(TEST_ARCHIVE, TEST_DIR, "speech_commands_test")
    except Exception as exc:
        print(f"  ✗ Failed to prepare raw dataset: {exc}")
        return False
    return True


# ── Example 01: Wake Word Detection ──────────────────────────────────────────

def prepare_01_wake_word(limit: int = 200) -> None:
    print("\n[1/5] Wake Word Detection → examples/01_wake_word/data/")
    data_dir = EXAMPLES / "01_wake_word" / "data"
    clear_data_dir(data_dir)

    # wake_word/ ← yes/ from test set
    n = copy_files(TEST_DIR / "yes", data_dir / "wake_word", limit=limit)
    print(f"  wake_word/: {n} files  (source: test/yes)")

    # background/ ← no/ + _silence_/ from test set
    n1 = copy_files(TEST_DIR / "no",       data_dir / "background", limit=limit // 2)
    n2 = copy_files(TEST_DIR / "_silence_", data_dir / "background", limit=limit // 2)
    print(f"  background/: {n1 + n2} files  (source: test/no + test/_silence_)")

    # noise/ ← real background noise WAVs
    noise_dst = data_dir / "noise"
    noise_dst.mkdir(parents=True, exist_ok=True)
    for f in (TRAIN_DIR / "_background_noise_").glob("*.wav"):
        shutil.copy2(f, noise_dst / f.name)
    n = len(list(noise_dst.glob("*.wav")))
    print(f"  noise/: {n} files  (source: train/_background_noise_)")


# ── Example 02: Speech Commands ──────────────────────────────────────────────

def prepare_02_speech_commands(limit: int = 200) -> None:
    print("\n[2/5] Speech Commands → examples/02_speech_commands/data/")
    data_dir = EXAMPLES / "02_speech_commands" / "data"
    clear_data_dir(data_dir)

    commands = ["yes", "no", "up", "down", "go", "stop"]
    for cmd in commands:
        src = TEST_DIR / cmd
        if not src.exists():
            print(f"  ✗ Missing: {src}")
            continue
        n = copy_files(src, data_dir / cmd, limit=limit)
        print(f"  {cmd}/: {n} files  (source: test/{cmd})")


# ── Example 03: Environmental Sounds ─────────────────────────────────────────

def prepare_03_environmental_sounds(limit: int = 200) -> None:
    print("\n[3/5] Environmental Sounds → examples/03_environmental_sounds/data/")
    data_dir = EXAMPLES / "03_environmental_sounds" / "data"
    clear_data_dir(data_dir)

    classes = {
        "dog":   TRAIN_DIR / "dog",
        "cat":   TRAIN_DIR / "cat",
        "bird":  TRAIN_DIR / "bird",
        "happy": TRAIN_DIR / "happy",
        "house": TRAIN_DIR / "house",
    }
    for label, src in classes.items():
        if not src.exists():
            print(f"  ✗ Missing: {src}")
            continue
        n = copy_files(src, data_dir / label, limit=limit)
        print(f"  {label}/: {n} files  (source: train/{label})")


# ── Example 04: Speaker Verification ─────────────────────────────────────────

def prepare_04_speaker_verification(n_speakers: int = 6,
                                     utterances_per_speaker: int = 20) -> None:
    print("\n[4/5] Speaker Verification → examples/04_speaker_verification/data/")
    data_dir = EXAMPLES / "04_speaker_verification" / "data"
    clear_data_dir(data_dir)

    # Collect utterances per speaker across ALL word classes
    speaker_utterances: dict[str, list[Path]] = defaultdict(list)
    for word_dir in sorted(TRAIN_DIR.iterdir()):
        if not word_dir.is_dir() or word_dir.name.startswith("_"):
            continue
        for f in word_dir.glob("*.wav"):
            speaker_id = f.stem.split("_nohash_")[0]
            speaker_utterances[speaker_id].append(f)

    qualified = [
        (spk, files)
        for spk, files in speaker_utterances.items()
        if len(files) >= utterances_per_speaker
    ]
    qualified.sort(key=lambda x: -len(x[1]))
    selected = qualified[:n_speakers]

    print(f"  Found {len(qualified)} speakers with ≥{utterances_per_speaker} utterances")

    manifest_rows = []
    for i, (speaker_id, files) in enumerate(selected, 1):
        label = f"speaker_{i:03d}"
        dst = data_dir / label
        dst.mkdir(parents=True, exist_ok=True)
        random.shuffle(files)
        chosen = files[:utterances_per_speaker]
        for f in chosen:
            # Prefix with word class to avoid filename collisions
            dst_name = f"{f.parent.name}_{f.name}"
            shutil.copy2(f, dst / dst_name)
        words_used = len(set(f.parent.name for f in chosen))
        print(f"  {label}/: {len(chosen)} files across {words_used} words  "
              f"(speaker_id={speaker_id})")
        manifest_rows.append((label, speaker_id, len(chosen)))

    # Write speaker manifest
    manifest_path = data_dir / "speaker_manifest.txt"
    with open(manifest_path, "w") as mf:
        mf.write("label,speaker_id,utterances\n")
        for label, speaker_id, n in manifest_rows:
            mf.write(f"{label},{speaker_id},{n}\n")
    print(f"  speaker_manifest.txt written")


# ── Example 05: Speech Enhancement ───────────────────────────────────────────

def prepare_05_speech_enhancement(limit: int = 100) -> None:
    print("\n[5/5] Speech Enhancement → examples/05_speech_enhancement/data/")
    data_dir = EXAMPLES / "05_speech_enhancement" / "data"
    clear_data_dir(data_dir)

    # clean_speech/ ← yes + no from test set
    n1 = copy_files(TEST_DIR / "yes", data_dir / "clean_speech", limit=limit)
    n2 = copy_files(TEST_DIR / "no",  data_dir / "clean_speech", limit=limit)
    print(f"  clean_speech/: {n1 + n2} files  (source: test/yes + test/no)")

    # noise/ ← real background noise WAVs
    noise_dst = data_dir / "noise"
    noise_dst.mkdir(parents=True, exist_ok=True)
    for f in (TRAIN_DIR / "_background_noise_").glob("*.wav"):
        shutil.copy2(f, noise_dst / f.name)
    n = len(list(noise_dst.glob("*.wav")))
    print(f"  noise/: {n} files  (source: train/_background_noise_)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Graphyn — Preparing real Speech Commands dataset")
    print("=" * 60)
    print("Data will be copied into examples/{n}/data/ directories.")
    print("Examples are fully self-contained — no workspace pollution.")

    print("\nEnsuring raw dataset is available...")
    if not ensure_raw_data():
        print("\n✗ Failed to prepare raw dataset. Aborting.")
        return

    if not check_prerequisites():
        print("\n✗ Dataset preparation incomplete. Aborting.")
        return

    prepare_01_wake_word(limit=200)
    prepare_02_speech_commands(limit=200)
    prepare_03_environmental_sounds(limit=200)
    prepare_04_speaker_verification(n_speakers=6, utterances_per_speaker=20)
    prepare_05_speech_enhancement(limit=100)

    print("\n" + "=" * 60)
    print("Done! Example data directories:")
    for ex_dir in sorted(EXAMPLES.iterdir()):
        data_dir = ex_dir / "data"
        if data_dir.exists():
            subdirs = [d for d in data_dir.iterdir() if d.is_dir()]
            total = sum(len(list(d.glob("*.wav"))) for d in subdirs)
            print(f"  {ex_dir.name}/data/: {len(subdirs)} labels, {total} WAV files")

    print("\nYou can now run any example:")
    for ex_dir in sorted(EXAMPLES.iterdir()):
        sdk = ex_dir / "run_sdk.py"
        if sdk.exists():
            print(f"  venv/bin/python {sdk}")


if __name__ == "__main__":
    main()
