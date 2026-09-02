# Example 22 — Call analytics

Golden path: ingest audio → condition → **ASR** → PII redact → structured extract → eval gate → webhook.

- `pipeline.graph.json` — CI-safe **mock** providers (no keys, unit/e2e).
- `pipeline.live.graph.json` — **Deepgram** ASR + **OpenAI** structured extract + real HTTP webhook.

## Plugins

```bash
for p in asr_transcribe pii_redact structured_llm eval_gate http_webhook; do
  python -m app.cli.main plugin install "PluginPackage/Common/${p}/" --upgrade
done
python -m app.cli.main plugin install PluginPackage/Audio/dataset_ingest/ --upgrade
python -m app.cli.main plugin install PluginPackage/Audio/audio_conditioner/ --upgrade
```

## Secrets (never in Graph IR)

| Name | Used by live graph |
|---|---|
| `DEEPGRAM_API_KEY` | `asr_transcribe` provider=`deepgram` |
| `OPENAI_API_KEY` | `structured_llm` provider=`openai_compat` |
| `GRAPHYN_WEBHOOK_HMAC` | optional webhook HMAC (`hmac_env`) |

```bash
export DEEPGRAM_API_KEY=...
export OPENAI_API_KEY=...
python -m app.cli.main secrets set DEEPGRAM_API_KEY
python -m app.cli.main secrets set OPENAI_API_KEY
python -m app.cli.main secrets list   # names only
```

Node lookup: secret store, then process env. Missing keys fail with a clear error naming `DEEPGRAM_API_KEY` / `OPENAI_API_KEY`.

Edit `http_webhook_6.config.url` in the live graph to your callback (example.com will 404/fail closed).

## Run mock (CI)

```bash
python examples/prepare_real_data.py   # optional speech-commands clips
python -m app.cli.main run --graph examples/22_call_analytics/pipeline.graph.json
```

## Run live (Deepgram + OpenAI)

```bash
python -m app.cli.main run --graph examples/22_call_analytics/pipeline.live.graph.json
```

AssemblyAI alternative: set node `provider` to `assemblyai` and `graphyn secrets set ASSEMBLYAI_API_KEY`. Create returns a job id; the node **polls** until `status=completed` (create JSON is not the transcript).
