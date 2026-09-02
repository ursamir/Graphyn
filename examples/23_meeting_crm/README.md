# Example 23 — Meeting CRM extract

asr_transcribe → pii_redact → structured_llm (pain, objections, next_step, owner) → eval_gate → http_webhook

`dataset_ingest` is included so the graph is runnable; it feeds audio into ASR.

## Env vars

Same as example 22 (`OPENAI_API_KEY`, `ASSEMBLYAI_API_KEY`, `DEEPGRAM_API_KEY`). Mock providers need none.

## Run

```bash
python -m app.cli.main plugin install PluginPackage/Common/asr_transcribe/ --upgrade
python -m app.cli.main plugin install PluginPackage/Common/pii_redact/ --upgrade
python -m app.cli.main plugin install PluginPackage/Common/structured_llm/ --upgrade
python -m app.cli.main plugin install PluginPackage/Common/eval_gate/ --upgrade
python -m app.cli.main plugin install PluginPackage/Common/http_webhook/ --upgrade
python -m app.cli.main plugin install PluginPackage/Audio/dataset_ingest/ --upgrade

python -m app.cli.main run --graph examples/23_meeting_crm/pipeline.graph.json
```

## Live vs mock

Live: `pipeline.live.graph.json` uses openai_compat ASR+LLM (`OPENAI_API_KEY`). Keep `pipeline.graph.json` for mock CI.
