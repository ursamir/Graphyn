# Example 24 — Captions

dataset_ingest → asr_transcribe (mock word timings) → caption_export (SRT + VTT + JSON)

## Output

`examples/24_captions/output/captions.{srt,vtt,json}`

## Run with mock ASR

```bash
python -m app.cli.main plugin install PluginPackage/Audio/dataset_ingest/ --upgrade
python -m app.cli.main plugin install PluginPackage/Common/asr_transcribe/ --upgrade
python -m app.cli.main plugin install PluginPackage/Common/caption_export/ --upgrade

python -m app.cli.main run --graph examples/24_captions/pipeline.graph.json
```
