# WakeWord pack

Five Graphyn nodes that train and run a custom wake word ("hey graphyn") end to end.
They wrap the upstream [livekit-wakeword](https://github.com/livekit/livekit-wakeword)
library (Apache-2.0, `pip install 'livekit-wakeword[train,export]>=0.2.1,<0.3'`), which is
installed into each plugin's isolated venv.

| Node | What it does |
|------|--------------|
| `wakeword_data_gen` | Synthesises positive clips of the target phrase(s), adversarial negatives (phonetically similar phrases from CMUdict, partial phrases, `custom_negative_phrases`) and background-noise clips from an optional `background` audio input. TTS: `piper_vits` (Piper VITS LibriTTS, 904 speakers with SLERP blending; needs the `espeak-ng` binary, checkpoint ≈174 MB downloaded once from the livekit-wakeword GitHub release), `mms` (Meta MMS-TTS via transformers; no system binary) or `auto`. |
| `wakeword_feature_extract` | Augments each clip (parametric EQ, tanh distortion, optional room-impulse convolution, background mixing at 5–15 dB SNR), aligns it to a 2 s window and extracts `(N, 16, 96)` speech embeddings through the bundled ONNX mel-spectrogram + Google speech-embedding models. `download_rirs` fetches the MIT impulse responses (≈8 MB, huggingface.co). |
| `wakeword_train` | livekit-wakeword's 3-phase trainer (conv-attention / DNN / RNN head, focal loss, mix-up, label smoothing, negative-weight ramp, checkpoint averaging, threshold search on the test split). Optional ACAV100M features (≈16 GB) are used when present. |
| `wakeword_export_onnx` | Exports the head to ONNX (`embeddings (B,16,96) → score (B,1)`), optional INT8 dynamic quantisation, and verifies both files against PyTorch with onnxruntime. |
| `wakeword_infer` | Detects the wake word in audio files: sliding 2 s windows (hop 0.1 s) through the front end and the exported head, merged detections with times, a silence floor and the run's tuned threshold. Outputs `PredictionResult`s. |

Stages pass a `WakeWordRun` (`model_dir` in the upstream layout plus a `wakeword_run.json`
manifest), so any stage can also start from an existing directory via `config.model_dir`.

Quality notes: the templates use a few hundred synthetic clips so they finish in minutes on
CPU. A production model needs thousands of clips per split, real background audio, RIRs and
ideally the ACAV100M negative features. Without ACAV100M, `align_negatives="end"` (default)
stops the classifier from learning the word's position in the window as a shortcut.

The other directories in this folder (`cli.py`, `config.py`, `data_generator/`, `training/`, …)
are an older vendored copy of the library. The nodes do not import it, and it does not import
on its own (its relative imports expect the upstream module names `models/`, `data/`,
`export/` and `eval/`). It is kept only for reference.
