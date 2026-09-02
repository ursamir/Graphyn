# Example 22 — Call analytics

Offline-first pipeline: ingest audio, condition it, mock-transcribe, redact PII, extract a JSON call record, fail-closed on missing keys, POST a completion webhook.

dataset_ingest → audio_conditioner → asr_transcribe → pii_redact → structured_llm → eval_gate → http_webhook

## What it produces

- A mock `Transcript` (word timings from clip duration)
- Redacted transcript + audit list
- `StructuredDocument` with `summary`, `sentiment`, `topics`, `action_items`, `customer_id` (mock placeholders)
- HTTP POST of that JSON to the webhook URL (fails if the URL is unreachable)

## Plugins

Install once:

```bash
for p in asr_transcribe pii_redact structured_llm eval_gate http_webhook; do
  python -m app.cli.main plugin install "PluginPackage/Common/${p}/" --upgrade
done
python -m app.cli.main plugin install PluginPackage/Audio/dataset_ingest/ --upgrade
python -m app.cli.main plugin install PluginPackage/Audio/audio_conditioner/ --upgrade
```

## Env vars (real providers only)

| Variable | Used by |
|---|---|
| `OPENAI_API_KEY` | `asr_transcribe` provider=`openai_compat`, `structured_llm` provider=`openai_compat` |
| `OPENAI_BASE_URL` | optional OpenAI-compatible base (default `https://api.openai.com/v1`) |
| `ASSEMBLYAI_API_KEY` | `asr_transcribe` provider=`assemblyai` |
| `DEEPGRAM_API_KEY` | `asr_transcribe` provider=`deepgram` |

Leave providers at `mock` to run with no keys.

Edit `http_webhook_6.config.url` (or HMAC secret) before a real callback.

## Run with mock providers

```bash
# optional: prepare Speech Commands clips used as dummy call audio
python examples/prepare_real_data.py

python -m app.cli.main run --graph examples/22_call_analytics/pipeline.graph.json
```

The default webhook URL is `https://example.com/webhooks/call-analytics`. Point it at a local listener, or expect the last node to error if that host does not accept the POST.
