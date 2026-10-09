# Video plugin pack

Ten plugins for video datasets and analysis. Media work is done with the
`ffmpeg` / `ffprobe` binaries (present in the Graphyn image); model nodes run
in isolated venvs.

| Plugin | What it does | Runtime / deps |
|---|---|---|
| `video_ingest` | Find videos in a file/folder, ffprobe duration/fps/size/codec/audio | inprocess, ffprobe |
| `video_quality_gate` | Duration/resolution/fps/audio checks + black/frozen/silent ratios (ffmpeg blackdetect/freezedetect/silencedetect); skip/flag/fail | inprocess, ffmpeg |
| `scene_detect` | Shot boundaries from ffmpeg's scene-change score, min scene length | inprocess, ffmpeg |
| `clip_segment` | Cut by scenes or fixed windows; writes H.264 clips (or virtual segments) | inprocess, ffmpeg + libx264 |
| `frame_sample` | JPEG frames by fps / every N-th / keyframes / uniform N with exact timestamps | inprocess, ffmpeg |
| `video_caption` | Caption frames with a vision LLM: local Ollama (`moondream`, `llava-phi3`) or an OpenAI-compatible endpoint (needs a credential) | inprocess, Graphyn LLM client |
| `video_embed` | CLIP (`openai/clip-vit-base-patch32`) embeddings, mean over frames, optional zero-shot labels | isolated, torch + transformers |
| `action_classify` | Kinetics-400 action recognition (torchvision r3d_18 / mc3_18 / r2plus1d_18) or a custom ONNX model | isolated, torch + torchvision (+ onnxruntime) |
| `av_align` | Extract a video's audio as AudioSamples, or align an external recording with GCC-PHAT (offset + confidence) | inprocess, ffmpeg + scipy |
| `video_exporter` | Label-per-folder dataset + `manifest.jsonl`/`manifest.csv` with per-clip captions/predictions | inprocess, ffmpeg |

Items between Video nodes are `VideoSample` (path + `start_s`/`end_s`
segment + probe facts), `SceneBoundary`, `ImageSample` (frames),
`CaptionRecord`, `EmbeddingVector` and `PredictionResult`. Every node also
accepts plain dicts with the same fields, so outputs of isolated nodes flow
on unchanged.

Each plugin ships its own copy of `_vio.py` (shared ffmpeg helpers) so the
plugins install independently.

Sample media: `examples/31_video_demo/data/clip.mp4` (Big Buck Bunny trailer,
CC-BY 3.0 Blender Foundation). Tests: `unit_test/plugins/video/`.
