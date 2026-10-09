# Example 24 — Captions

dataset_ingest → asr_transcribe (word timings) → caption_export (SRT + VTT + JSON)

| Graph | ASR | Needs |
|---|---|---|
| `pipeline.graph.json` | local Whisper (`tiny`) | nothing — runs offline |
| `pipeline.live.graph.json` | Deepgram `nova-2` | `DEEPGRAM_API_KEY` |

## Output

`workspace/artifacts/captions/` — `captions.srt`, `captions.vtt`, `captions.json`.

## Run

```bash
python -m app.cli.main plugin install PluginPackage/Audio/dataset_ingest/ --upgrade
python -m app.cli.main plugin install PluginPackage/Common/asr_transcribe/ --upgrade
python -m app.cli.main plugin install PluginPackage/Common/caption_export/ --upgrade

python -m app.cli.main run --graph examples/24_captions/pipeline.graph.json
```

Live: `python -m app.cli.main secrets set DEEPGRAM_API_KEY`, then run `pipeline.live.graph.json`.
