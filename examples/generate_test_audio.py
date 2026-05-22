#!/usr/bin/env python3
"""
generate_test_audio.py — Generate synthetic test audio for all AudioBuilder examples.

Creates realistic-sounding synthetic audio clips for each use case using only
numpy and soundfile. No external audio dependencies required.

Usage:
    venv/bin/python examples/generate_test_audio.py

Output directories created:
    workspace/datasets/input/wake_word/
    workspace/datasets/input/background/
    workspace/datasets/input/yes/
    workspace/datasets/input/no/
    workspace/datasets/input/stop/
    workspace/datasets/input/go/
    workspace/datasets/input/up/
    workspace/datasets/input/down/
    workspace/datasets/input/dog_bark/
    workspace/datasets/input/car_horn/
    workspace/datasets/input/siren/
    workspace/datasets/input/footsteps/
    workspace/datasets/input/rain/
    workspace/datasets/input/speaker_001/
    workspace/datasets/input/speaker_002/
    workspace/datasets/input/speaker_003/
    workspace/datasets/input/speaker_004/
    workspace/datasets/input/clean_speech/
    workspace/datasets/input/noisy_speech/  (for enhancement example)
"""
from __future__ import annotations

import os
import sys
import numpy as np
import soundfile as sf
from pathlib import Path

# ── Ensure we run relative to workspace root ──────────────────────────────────
# This allows running the script from any directory:
#   venv/bin/python examples/generate_test_audio.py
_SCRIPT_DIR = Path(__file__).parent
_WORKSPACE_ROOT = _SCRIPT_DIR.parent
os.chdir(_WORKSPACE_ROOT)

# ── Constants ─────────────────────────────────────────────────────────────────

WORKSPACE = Path("workspace/datasets/input")
SAMPLE_RATE = 16000
RNG = np.random.default_rng(42)


# ── Synthesis helpers ─────────────────────────────────────────────────────────

def sine_wave(freq: float, duration_s: float, sr: int = SAMPLE_RATE,
              amplitude: float = 0.5) -> np.ndarray:
    """Generate a pure sine wave."""
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def multi_sine(freqs: list[float], duration_s: float, sr: int = SAMPLE_RATE,
               amplitude: float = 0.4) -> np.ndarray:
    """Generate a mixture of sine waves (simulates formant-like speech)."""
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    signal = np.zeros(len(t), dtype=np.float32)
    for f in freqs:
        signal += amplitude / len(freqs) * np.sin(2 * np.pi * f * t)
    return signal.astype(np.float32)


def apply_envelope(signal: np.ndarray, attack_ms: float = 20.0,
                   release_ms: float = 30.0, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Apply a simple attack-sustain-release amplitude envelope."""
    n = len(signal)
    n_attack = min(int(attack_ms * sr / 1000), n // 4)
    n_release = min(int(release_ms * sr / 1000), n // 4)

    env = np.ones(n, dtype=np.float32)
    if n_attack > 0:
        env[:n_attack] = np.linspace(0, 1, n_attack)
    if n_release > 0:
        env[n - n_release:] = np.linspace(1, 0, n_release)

    return (signal * env).astype(np.float32)


def add_noise(signal: np.ndarray, snr_db: float = 30.0) -> np.ndarray:
    """Add white noise at a given SNR."""
    signal_rms = np.sqrt(np.mean(signal ** 2)) + 1e-9
    noise_rms = signal_rms / (10 ** (snr_db / 20))
    noise = RNG.standard_normal(len(signal)).astype(np.float32) * noise_rms
    return np.clip(signal + noise, -1.0, 1.0).astype(np.float32)


def white_noise(duration_s: float, sr: int = SAMPLE_RATE,
                amplitude: float = 0.3) -> np.ndarray:
    """Generate white noise."""
    n = int(sr * duration_s)
    return (RNG.standard_normal(n) * amplitude).astype(np.float32)


def pink_noise(duration_s: float, sr: int = SAMPLE_RATE,
               amplitude: float = 0.3) -> np.ndarray:
    """Generate pink noise (1/f) via spectral shaping."""
    n = int(sr * duration_s)
    white = RNG.standard_normal(n)
    fft = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n)
    freqs[0] = 1e-9  # avoid division by zero
    pink_filter = 1.0 / np.sqrt(freqs)
    pink_filter[0] = 0.0
    pink = np.fft.irfft(fft * pink_filter, n=n)
    pink = pink / (np.abs(pink).max() + 1e-9) * amplitude
    return pink.astype(np.float32)


def brown_noise(duration_s: float, sr: int = SAMPLE_RATE,
                amplitude: float = 0.3) -> np.ndarray:
    """Generate brown noise (1/f²) via cumulative sum of white noise."""
    n = int(sr * duration_s)
    white = RNG.standard_normal(n)
    brown = np.cumsum(white)
    brown = brown / (np.abs(brown).max() + 1e-9) * amplitude
    return brown.astype(np.float32)


def speech_like(duration_s: float, sr: int = SAMPLE_RATE,
                fundamental: float = 150.0,
                formants: list[float] | None = None) -> np.ndarray:
    """
    Generate a speech-like signal with a fundamental frequency and formants.
    Simulates voiced speech by modulating harmonics with a slow amplitude envelope.
    """
    if formants is None:
        formants = [fundamental * 2, fundamental * 5, fundamental * 9]

    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    signal = np.zeros(len(t), dtype=np.float32)

    # Fundamental + harmonics
    for harmonic in range(1, 8):
        freq = fundamental * harmonic
        if freq < sr / 2:
            amp = 0.3 / harmonic
            signal += amp * np.sin(2 * np.pi * freq * t).astype(np.float32)

    # Formant resonances
    for f_freq in formants:
        if f_freq < sr / 2:
            signal += 0.15 * np.sin(2 * np.pi * f_freq * t).astype(np.float32)

    # Slow amplitude modulation (simulates syllable rhythm ~4 Hz)
    mod_freq = 4.0 + RNG.uniform(-0.5, 0.5)
    modulation = 0.5 + 0.5 * np.sin(2 * np.pi * mod_freq * t)
    signal = (signal * modulation).astype(np.float32)

    # Normalize
    peak = np.abs(signal).max()
    if peak > 0:
        signal = signal / peak * 0.7

    return apply_envelope(signal, attack_ms=30, release_ms=50, sr=sr)


def save_wav(path: Path, data: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    """Save a numpy array as a WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Ensure float32 and clipped
    data = np.clip(data.astype(np.float32), -1.0, 1.0)
    sf.write(str(path), data, sr)


# ── Example 1: Wake Word Detection ───────────────────────────────────────────

def generate_wake_word(n_samples: int = 8) -> None:
    """
    Generate wake word clips (short speech bursts) and background noise clips.
    wake_word: 1-2s speech-like signals simulating "Hey Assistant"
    background: ambient noise (white, pink, brown noise mixtures)
    """
    print("  Generating wake_word samples...")
    wake_dir = WORKSPACE / "wake_word"
    for i in range(n_samples):
        duration = RNG.uniform(1.0, 2.0)
        # Vary fundamental to simulate different speakers
        fundamental = RNG.uniform(100, 220)
        formants = [fundamental * k for k in [3, 6, 10]]
        signal = speech_like(duration, SAMPLE_RATE, fundamental, formants)
        signal = add_noise(signal, snr_db=RNG.uniform(25, 40))
        save_wav(wake_dir / f"wake_{i:03d}.wav", signal)

    print("  Generating background samples...")
    bg_dir = WORKSPACE / "background"
    noise_generators = [white_noise, pink_noise, brown_noise]
    for i in range(n_samples):
        duration = RNG.uniform(1.5, 3.0)
        gen = noise_generators[i % len(noise_generators)]
        amplitude = RNG.uniform(0.1, 0.4)
        signal = gen(duration, SAMPLE_RATE, amplitude)
        # Sometimes mix two noise types
        if RNG.random() > 0.5:
            signal2 = noise_generators[(i + 1) % len(noise_generators)](
                duration, SAMPLE_RATE, amplitude * 0.5
            )
            signal = np.clip(signal + signal2, -1.0, 1.0).astype(np.float32)
        save_wav(bg_dir / f"bg_{i:03d}.wav", signal)


# ── Example 2: Speech Commands ────────────────────────────────────────────────

# Each command has a characteristic frequency profile
COMMAND_PROFILES = {
    "yes":  {"fundamental": 180, "formants": [540, 1800, 2700], "duration": (0.5, 1.0)},
    "no":   {"fundamental": 160, "formants": [400, 1200, 2400], "duration": (0.3, 0.8)},
    "stop": {"fundamental": 140, "formants": [600, 1500, 2500], "duration": (0.6, 1.2)},
    "go":   {"fundamental": 200, "formants": [500, 1600, 2800], "duration": (0.4, 0.9)},
    "up":   {"fundamental": 220, "formants": [700, 2000, 3000], "duration": (0.3, 0.7)},
    "down": {"fundamental": 130, "formants": [450, 1100, 2200], "duration": (0.5, 1.0)},
}


def generate_speech_commands(n_per_command: int = 8) -> None:
    """Generate speech command clips with distinct frequency profiles per command."""
    print("  Generating speech command samples...")
    for command, profile in COMMAND_PROFILES.items():
        cmd_dir = WORKSPACE / command
        for i in range(n_per_command):
            duration = RNG.uniform(*profile["duration"])
            # Vary fundamental slightly per sample
            fundamental = profile["fundamental"] * RNG.uniform(0.9, 1.1)
            formants = [f * RNG.uniform(0.95, 1.05) for f in profile["formants"]]
            signal = speech_like(duration, SAMPLE_RATE, fundamental, formants)
            signal = add_noise(signal, snr_db=RNG.uniform(20, 35))
            save_wav(cmd_dir / f"{command}_{i:03d}.wav", signal)


# ── Example 3: Environmental Sounds ──────────────────────────────────────────

def dog_bark(duration_s: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Simulate a dog bark: short burst of mid-frequency energy."""
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    # Bark: ~500-1500 Hz burst with fast decay
    signal = np.zeros(len(t), dtype=np.float32)
    bark_freqs = [500, 800, 1200, 1500]
    for f in bark_freqs:
        signal += 0.2 * np.sin(2 * np.pi * f * t)
    # Fast exponential decay envelope
    decay = np.exp(-t * 8)
    signal = (signal * decay).astype(np.float32)
    signal = add_noise(signal, snr_db=20)
    return signal / (np.abs(signal).max() + 1e-9) * 0.7


def car_horn(duration_s: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Simulate a car horn: sustained dual-tone."""
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    # Typical car horn: ~392 Hz (G4) + ~494 Hz (B4)
    signal = (0.4 * np.sin(2 * np.pi * 392 * t) +
              0.4 * np.sin(2 * np.pi * 494 * t)).astype(np.float32)
    signal = apply_envelope(signal, attack_ms=50, release_ms=100, sr=sr)
    return signal / (np.abs(signal).max() + 1e-9) * 0.7


def siren(duration_s: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Simulate an emergency siren: frequency-swept tone."""
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    # Sweep between 700 Hz and 1200 Hz at ~1 Hz rate
    sweep_rate = 1.0
    freq = 700 + 250 * np.sin(2 * np.pi * sweep_rate * t)
    phase = np.cumsum(2 * np.pi * freq / sr)
    signal = (0.6 * np.sin(phase)).astype(np.float32)
    return signal / (np.abs(signal).max() + 1e-9) * 0.7


def footsteps(duration_s: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Simulate footsteps: periodic low-frequency transients."""
    n = int(sr * duration_s)
    signal = np.zeros(n, dtype=np.float32)
    step_interval = int(sr * 0.5)  # ~2 steps per second
    step_duration = int(sr * 0.08)  # 80ms per step

    for step_start in range(0, n - step_duration, step_interval):
        t_step = np.linspace(0, 0.08, step_duration)
        # Low-frequency thud
        step = (0.5 * np.sin(2 * np.pi * 80 * t_step) *
                np.exp(-t_step * 40)).astype(np.float32)
        end = min(step_start + step_duration, n)
        signal[step_start:end] += step[:end - step_start]

    signal = add_noise(signal, snr_db=15)
    return signal / (np.abs(signal).max() + 1e-9) * 0.6


def rain_sound(duration_s: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Simulate rain: filtered noise with occasional drops."""
    signal = pink_noise(duration_s, sr, amplitude=0.3)
    # Add occasional high-frequency drops
    n = int(sr * duration_s)
    n_drops = int(duration_s * 20)
    for _ in range(n_drops):
        pos = RNG.integers(0, max(1, n - 100))
        drop_len = RNG.integers(50, 150)
        end = min(pos + drop_len, n)
        t_drop = np.linspace(0, 1, end - pos)
        drop = (0.1 * np.sin(2 * np.pi * 3000 * t_drop) *
                np.exp(-t_drop * 20)).astype(np.float32)
        signal[pos:end] += drop
    return np.clip(signal, -1.0, 1.0).astype(np.float32)


ENV_GENERATORS = {
    "dog_bark": dog_bark,
    "car_horn": car_horn,
    "siren": siren,
    "footsteps": footsteps,
    "rain": rain_sound,
}


def generate_environmental_sounds(n_per_class: int = 6) -> None:
    """Generate environmental sound clips with characteristic profiles."""
    print("  Generating environmental sound samples...")
    for label, generator in ENV_GENERATORS.items():
        sound_dir = WORKSPACE / label
        for i in range(n_per_class):
            duration = RNG.uniform(2.5, 4.5)
            signal = generator(duration, SAMPLE_RATE)
            save_wav(sound_dir / f"{label}_{i:03d}.wav", signal)


# ── Example 4: Speaker Verification ──────────────────────────────────────────

# Each speaker has a consistent fundamental frequency and formant pattern
SPEAKER_PROFILES = {
    "speaker_001": {"fundamental": 120, "formants": [700, 1200, 2500], "jitter": 0.02},
    "speaker_002": {"fundamental": 180, "formants": [800, 1600, 2800], "jitter": 0.03},
    "speaker_003": {"fundamental": 100, "formants": [600, 1100, 2300], "jitter": 0.015},
    "speaker_004": {"fundamental": 210, "formants": [900, 1800, 3000], "jitter": 0.025},
}


def generate_speaker_verification(n_per_speaker: int = 6) -> None:
    """
    Generate speaker verification clips. Each speaker has consistent vocal
    characteristics (fundamental frequency, formants) across utterances.
    """
    print("  Generating speaker verification samples...")
    for speaker_id, profile in SPEAKER_PROFILES.items():
        spk_dir = WORKSPACE / speaker_id
        for i in range(n_per_speaker):
            duration = RNG.uniform(3.0, 5.0)
            # Small per-utterance variation (jitter) but consistent speaker identity
            jitter = profile["jitter"]
            fundamental = profile["fundamental"] * (1 + RNG.uniform(-jitter, jitter))
            formants = [f * (1 + RNG.uniform(-jitter, jitter))
                        for f in profile["formants"]]
            signal = speech_like(duration, SAMPLE_RATE, fundamental, formants)
            signal = add_noise(signal, snr_db=RNG.uniform(25, 40))
            save_wav(spk_dir / f"utt_{i:03d}.wav", signal)


# ── Example 5: Speech Enhancement ────────────────────────────────────────────

def generate_speech_enhancement(n_samples: int = 8) -> None:
    """
    Generate clean speech clips for the speech enhancement example.
    The degradation_pipeline plugin will create the degraded versions.
    """
    print("  Generating speech enhancement samples...")
    clean_dir = WORKSPACE / "clean_speech"

    fundamentals = [120, 150, 180, 200, 130, 160, 190, 140]
    formant_sets = [
        [700, 1200, 2500],
        [800, 1600, 2800],
        [600, 1100, 2300],
        [900, 1800, 3000],
        [750, 1400, 2600],
        [650, 1300, 2400],
        [850, 1700, 2900],
        [700, 1500, 2700],
    ]

    for i in range(n_samples):
        duration = RNG.uniform(4.0, 6.0)
        fundamental = fundamentals[i % len(fundamentals)]
        formants = formant_sets[i % len(formant_sets)]
        signal = speech_like(duration, SAMPLE_RATE, fundamental, formants)
        # Clean speech: minimal noise
        signal = add_noise(signal, snr_db=45)
        save_wav(clean_dir / f"clean_{i:03d}.wav", signal)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Graphyn — Generating synthetic test audio")
    print("=" * 50)

    WORKSPACE.mkdir(parents=True, exist_ok=True)

    print("\n[1/5] Wake Word Detection...")
    generate_wake_word(n_samples=8)

    print("\n[2/5] Speech Commands...")
    generate_speech_commands(n_per_command=8)

    print("\n[3/5] Environmental Sounds...")
    generate_environmental_sounds(n_per_class=6)

    print("\n[4/5] Speaker Verification...")
    generate_speaker_verification(n_per_speaker=6)

    print("\n[5/5] Speech Enhancement...")
    generate_speech_enhancement(n_samples=8)

    # Summary
    print("\n" + "=" * 50)
    print("Done! Created the following directories:")
    for d in sorted(WORKSPACE.iterdir()):
        if d.is_dir():
            n_files = len(list(d.glob("*.wav")))
            print(f"  {d.relative_to(Path('.'))}/ ({n_files} WAV files)")

    print("\nYou can now run any example:")
    print("  venv/bin/python examples/01_wake_word/run_sdk.py")
    print("  venv/bin/python examples/02_speech_commands/run_sdk.py")
    print("  venv/bin/python examples/03_environmental_sounds/run_sdk.py")
    print("  venv/bin/python examples/04_speaker_verification/run_sdk.py")
    print("  venv/bin/python examples/05_speech_enhancement/run_sdk.py")


if __name__ == "__main__":
    main()
