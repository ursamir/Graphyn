# Example 26 — Nightly compliance

schedule_trigger (cron metadata) + dataset_ingest → asr_transcribe (mock) → pii_redact → eval_gate → if_switch → http_request (Slack mock) or csv_table.

The schedule node is a source with `event_trigger` so agents can bind a timer. Manual `execute_pipeline` still runs because `schedule_trigger.process()` emits a tick (ingest is the audio source).

## Plugins

```bash
for p in schedule_trigger asr_transcribe pii_redact eval_gate if_switch http_request csv_table; do
  python -m app.cli.main plugin install "PluginPackage/Common/${p}/" --upgrade
done
python -m app.cli.main plugin install PluginPackage/Audio/dataset_ingest/ --upgrade
```

Native Slack nodes are out of v1 — use `http_request` + `auth_env` (env var **name**, never the secret in IR).

```bash
python -m app.cli.main run --graph examples/26_nightly_compliance/pipeline.graph.json
```

## Live vs mock

Live: `pipeline.live.graph.json` uses openai_compat ASR and `http_request` + `auth_env=SLACK_BOT_TOKEN` (no native Slack node). Mock CI: `pipeline.graph.json`.
