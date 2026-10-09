# Example 28 — ASR + python_code fan-out → merge → eval → CSV

dataset_ingest fans out to `asr_transcribe` and `python_code` (restricted sandbox), then `merge` (append), `eval_gate`, `csv_table`.

| Graph | ASR | Needs |
|---|---|---|
| `pipeline.graph.json` | local Whisper (`tiny`) | nothing — runs offline |
| `pipeline.live.graph.json` | OpenAI-compatible | `OPENAI_API_KEY` |

Output: `workspace/artifacts/asr-eval-merge/merged.csv`.

```bash
for p in asr_transcribe python_code merge eval_gate csv_table; do
  python -m app.cli.main plugin install "PluginPackage/Common/${p}/" --upgrade
done
python -m app.cli.main plugin install PluginPackage/Audio/dataset_ingest/ --upgrade
python -m app.cli.main run --graph examples/28_asr_eval_merge/pipeline.graph.json
```
