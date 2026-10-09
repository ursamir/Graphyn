# Example 23 — Meeting CRM extract

dataset_ingest → asr_transcribe → pii_redact → structured_llm (pain, objections, next_step, owner) → eval_gate → store / deliver

| Graph | Providers | Needs |
|---|---|---|
| `pipeline.graph.json` | local Whisper (`tiny`), rule-based extract (`rule_based`), local `object_store` | nothing — runs offline |
| `pipeline.live.graph.json` | OpenAI-compatible ASR + LLM, `http_webhook` | `OPENAI_API_KEY`, a webhook URL |

Offline output: one JSON record per meeting under `workspace/artifacts/meeting-crm/store/meetings/`.
The rule-based extract only fills fields it can find in the transcript text; use the live graph for real CRM fields.

## Run

```bash
for p in asr_transcribe pii_redact structured_llm eval_gate object_store http_webhook; do
  python -m app.cli.main plugin install "PluginPackage/Common/${p}/" --upgrade
done
python -m app.cli.main plugin install PluginPackage/Audio/dataset_ingest/ --upgrade

python -m app.cli.main run --graph examples/23_meeting_crm/pipeline.graph.json
```

## Live

`python -m app.cli.main secrets set OPENAI_API_KEY`, set `http_webhook_5.config.url`, then run `pipeline.live.graph.json`.
Missing key or URL fails clearly at that node.
