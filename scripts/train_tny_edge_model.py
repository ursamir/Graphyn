#!/usr/bin/env python3
"""Train a tiny speech-commands classifier and export TF SavedModel for edge-deploy E2E."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow import keras

LABELS = ["yes", "no", "up", "down", "go", "stop"]
ROOT = Path(__file__).resolve().parents[1]
SPEECH_DIR = ROOT / "workspace" / "datasets" / "input" / "speech-commands"
# Docker image copies examples to /app/examples; workspace may symlink there
EX_SPEECH = ROOT / "examples" / "02_speech_commands" / "data"
OUT = ROOT / "workspace" / "artifacts" / "models" / "saved_model"
N_FRAMES = 101
N_MFCC = 40
SR_TARGET = 16000
MAX_PER_LABEL = 8


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if sw == 2:
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        x = np.frombuffer(raw, dtype=np.uint8).astype(np.float32) / 128.0 - 1.0
    if nch > 1:
        x = x.reshape(-1, nch).mean(axis=1)
    if rate != SR_TARGET and rate > 0:
        # naive resample
        duration = len(x) / rate
        new_len = int(duration * SR_TARGET)
        if new_len > 1:
            x = np.interp(np.linspace(0, len(x) - 1, new_len), np.arange(len(x)), x).astype(np.float32)
    return x


def feats(x: np.ndarray) -> np.ndarray:
    # pad/trim to 1s
    n = SR_TARGET
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    else:
        x = x[:n]
    # simple STFT magnitude buckets
    win = 400
    hop = 160
    frames = []
    for start in range(0, len(x) - win + 1, hop):
        frame = x[start : start + win] * np.hanning(win)
        spec = np.abs(np.fft.rfft(frame))
        # compress to N_MFCC bins
        edges = np.linspace(0, len(spec), N_MFCC + 1).astype(int)
        buckets = np.array([spec[edges[i] : edges[i + 1]].mean() if edges[i + 1] > edges[i] else 0.0 for i in range(N_MFCC)], dtype=np.float32)
        frames.append(np.log1p(buckets))
    arr = np.stack(frames)[:N_FRAMES]
    if arr.shape[0] < N_FRAMES:
        arr = np.pad(arr, ((0, N_FRAMES - arr.shape[0]), (0, 0)))
    return arr.astype(np.float32)


def speech_root() -> Path:
    if SPEECH_DIR.exists():
        return SPEECH_DIR
    if EX_SPEECH.exists():
        return EX_SPEECH
    raise FileNotFoundError(f"No speech-commands data at {SPEECH_DIR} or {EX_SPEECH}")


def build_dataset():
    root = speech_root()
    print("Loading speech-commands from", root)
    X, y = [], []
    for i, label in enumerate(LABELS):
        d = root / label
        wavs = sorted(d.glob("*.wav"))[:MAX_PER_LABEL]
        print(f"  {label}: {len(wavs)} wavs")
        for w in wavs:
            X.append(feats(load_wav(w)))
            y.append(i)
    if not X:
        raise RuntimeError(f"No wavs found under {root}")
    X = np.stack(X)[..., np.newaxis]
    y = np.array(y, dtype=np.int32)
    return X, y


def main() -> None:
    X, y = build_dataset()
    model = keras.Sequential(
        [
            keras.Input(shape=X.shape[1:]),
            keras.layers.Conv2D(8, 3, activation="relu"),
            keras.layers.MaxPool2D(),
            keras.layers.Conv2D(16, 3, activation="relu"),
            keras.layers.GlobalAveragePooling2D(),
            keras.layers.Dense(len(LABELS), activation="softmax"),
        ]
    )
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.fit(X, y, epochs=3, batch_size=8, verbose=1)
    OUT.mkdir(parents=True, exist_ok=True)
    tf.saved_model.save(model, str(OUT))
    print("saved", OUT)


if __name__ == "__main__":
    main()
