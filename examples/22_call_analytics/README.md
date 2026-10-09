# Example 22 — Call analytics

ingest audio → condition → **ASR** → PII redact (text + audio) → structured extract → eval gate → store / deliver.

| Graph | Providers | Needs |
|---|---|---|
| `pipeline.graph.json` | local Whisper (`tiny`), rule-based extract (`rule_based`), local `object_store` | nothing — runs offline |
| `pipeline.live.graph.json` | **Deepgram** ASR, **OpenAI** structured extract, `http_webhook` | `DEEPGRAM_API_KEY`, `OPENAI_API_KEY`, a webhook URL |

The offline graph writes one JSON record per call under `workspace/artifacts/call-analytics/store/calls/`.
The rule-based extract fills `summary` from the transcript; sentiment/topics stay best-effort.

## Plugins

```bash
for p in asr_transcribe pii_redact structured_llm eval_gate object_store http_webhook; do
  python -m app.cli.main plugin install "PluginPackage/Common/${p}/" --upgrade
done
python -m app.cli.main plugin install PluginPackage/Audio/dataset_ingest/ --upgrade
python -m app.cli.main plugin install PluginPackage/Audio/audio_conditioner/ --upgrade
```

## Run offline

```bash
venv/bin/python scripts/heal_e2e_local_data.py   # links example data into workspace/datasets/input/
python -m app.cli.main run --graph examples/22_call_analytics/pipeline.graph.json
```

## Run live (Deepgram + OpenAI)

Secrets never go in the Graph IR:

```bash
python -m app.cli.main secrets set DEEPGRAM_API_KEY
python -m app.cli.main secrets set OPENAI_API_KEY
python -m app.cli.main secrets set GRAPHYN_WEBHOOK_HMAC   # optional webhook signature
```

Set `http_webhook_6.config.url` to your callback (it ships empty), then:

```bash
python -m app.cli.main run --graph examples/22_call_analytics/pipeline.live.graph.json
```

Without the keys or URL the run fails at the first node that needs them, naming the missing variable.

AssemblyAI alternative: set the ASR `provider` to `assemblyai` and `secrets set ASSEMBLYAI_API_KEY`; the node polls the job until the transcript is ready.
