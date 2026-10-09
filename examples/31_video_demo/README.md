# 31 — Video demo

`data/clip.mp4` (built by `venv/bin/python examples/prepare_real_data.py`; example data is gitignored) is the 30 s *Big Buck Bunny* trailer re-encoded to 480×266
H.264 + 16 kHz AAC (626 KB). It drives the Video-pack templates
(`examples/templates/marketplace/tpl-video-*.graph.json`).

Attribution: *Big Buck Bunny* © 2008 Blender Foundation | www.bigbuckbunny.org,
licensed under Creative Commons Attribution 3.0
(https://creativecommons.org/licenses/by/3.0/). Re-encoded (scaled, trimmed
audio to mono 16 kHz); no other changes.

Try it:

```text
video_ingest(path=examples/31_video_demo/data) → video_quality_gate → scene_detect
  → clip_segment(scenes) → frame_sample → video_caption (local Ollama moondream)
  → video_exporter (manifest.jsonl with captions per clip)
```
