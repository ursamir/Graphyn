#!/usr/bin/env python3
"""Train a tiny speech-commands classifier and export TF SavedModel for edge-deploy E2E."""
from __future__ import annotations

import os
import wave
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow import keras

LABELS = ["yes", "no", "up", "down", "go", "stop"]
ROOT = Path("/workspace/Graphyn/workspace/datasets/input/speech-commands")
OUT = Path("/workspace/Graphyn/workspace/artifacts/models/saved_model")
N_FRAMES = 101
N_MFCC = 40  # feature bins (pseudo-MFCC via log-mag STFT buckets)
SR_TARGET = 16000


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        rate = w.getframerate()
        nframes = w.getnframes()
        raw = w.readframes(nframes)
    if sw == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if nch > 1:
        data = data.reshape(-1, nch).mean(axis=1)
    if rate != SR_TARGET and rate > 0:
        # nearest-neighbor resample (CPU-ok, tiny data)
        new_len = int(len(data) * SR_TARGET / rate)
        idx = (np.linspace(0, len(data) - 1, new_len)).astype(np.int64)
        data = data[idx]
    return data


def stft_log_buckets(y: np.ndarray, n_frames=N_FRAMES, n_bins=N_MFCC) -> np.ndarray:
    """Crude fixed-size log-magnitude feature map (101, 40)."""
    # Pad/trim to ~1s
    target = SR_TARGET
    if len(y) < target:
        y = np.pad(y, (0, target - len(y)))
    else:
        y = y[:target]
    hop = 160
    win = 400
    frames = []
    for i in range(n_frames):
        start = i * hop
        chunk = y[start : start + win]
        if len(chunk) < win:
            chunk = np.pad(chunk, (0, win - len(chunk)))
        # Hann window
        windowed = chunk * np.hanning(win)
        spec = np.abs(np.fft.rfft(windowed, n=512))
        # bucket to n_bins
        edges = np.linspace(0, len(spec), n_bins + 1).astype(int)
        buckets = np.array(
            [spec[edges[j] : edges[j + 1]].mean() if edges[j + 1] > edges[j] else 0.0 for j in range(n_bins)],
            dtype=np.float32,
        )
        frames.append(np.log1p(buckets))
    feat = np.stack(frames, axis=0)  # (101, 40)
    # per-utterance normalize
    feat = (feat - feat.mean()) / (feat.std() + 1e-6)
    return feat.astype(np.float32)


def build_dataset():
    X, y = [], []
    for li, label in enumerate(LABELS):
        d = ROOT / label
        wavs = sorted(d.glob("*.wav"))
        if not wavs:
            # follow symlink targets
            wavs = sorted(Path(os.path.realpath(d)).glob("*.wav"))
        print(f"  {label}: {len(wavs)} wavs")
        for p in wavs:
            audio = load_wav(p)
            feat = stft_log_buckets(audio)
            X.append(feat)
            y.append(li)
    X = np.stack(X)[..., np.newaxis]  # (N, 101, 40, 1)
    y = np.array(y, dtype=np.int32)
    return X, y


def build_tiny_model(n_classes: int) -> keras.Model:
    inp = keras.Input(shape=(N_FRAMES, N_MFCC, 1), name="features")
    x = keras.layers.Conv2D(8, (3, 3), activation="relu", padding="same")(inp)
    x = keras.layers.MaxPooling2D((2, 2))(x)
    x = keras.layers.Conv2D(16, (3, 3), activation="relu", padding="same")(x)
    x = keras.layers.GlobalAveragePooling2D()(x)
    x = keras.layers.Dropout(0.2)(x)
    out = keras.layers.Dense(n_classes, activation="softmax", name="probs")(x)
    model = keras.Model(inp, out, name="tny_speech_commands")
    model.compile(
        optimizer=keras.optimizers.Adam(1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def main():
    print("Loading speech-commands from", ROOT)
    X, y = build_dataset()
    print("X", X.shape, "y", y.shape, "classes", {LABELS[i]: int((y == i).sum()) for i in range(len(LABELS))})

    # tiny train/val split
    rng = np.random.default_rng(42)
    idx = rng.permutation(len(X))
    n_val = max(6, len(X) // 5)
    val_idx, tr_idx = idx[:n_val], idx[n_val:]
    Xtr, ytr = X[tr_idx], y[tr_idx]
    Xva, yva = X[val_idx], y[val_idx]

    model = build_tiny_model(len(LABELS))
    model.summary()
    model.fit(
        Xtr,
        ytr,
        validation_data=(Xva, yva),
        epochs=3,
        batch_size=8,
        verbose=2,
    )

    OUT.mkdir(parents=True, exist_ok=True)
    # Clear previous
    for p in OUT.iterdir():
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            import shutil
            shutil.rmtree(p)

    # Export SavedModel (TF 2.x)
    tf.saved_model.save(model, str(OUT))
    # Also keep keras sidecar + labels + repr for int8 if needed later
    model.save(str(OUT.parent / "model.keras"))
    (OUT / "labels.txt").write_text("\n".join(LABELS) + "\n")
    # representative samples for potential int8
    np.save(str(OUT / "X_train_repr.npy"), Xtr[: min(32, len(Xtr))].astype(np.float32))
    print("Saved SavedModel ->", OUT)
    print("Saved keras ->", OUT.parent / "model.keras")
    # quick size
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"SavedModel bytes: {total}")


if __name__ == "__main__":
    main()
