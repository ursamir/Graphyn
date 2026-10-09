# Example 26 — Nightly compliance

schedule_trigger (cron metadata) + dataset_ingest → asr_transcribe → pii_redact → eval_gate → if_switch → flagged / report

The schedule node is a source with `event_trigger` so a timer can be bound; a manual run still works because
`schedule_trigger` emits one tick and `dataset_ingest` supplies the audio.

| Graph | ASR | Flagged branch | Needs |
|---|---|---|---|
| `pipeline.graph.json` | local Whisper (`tiny`) | `csv_table` → `workspace/artifacts/nightly-compliance/flagged.csv` | nothing — runs offline |
| `pipeline.live.graph.json` | OpenAI-compatible | Slack `chat.postMessage` via `http_request` + `auth_env=SLACK_BOT_TOKEN` | `OPENAI_API_KEY`, `SLACK_BOT_TOKEN` |

Both graphs write the unflagged rows to `workspace/artifacts/nightly-compliance/compliance.csv`
(`csv_table` paths are relative to the workspace).

## Plugins

```bash
for p in schedule_trigger asr_transcribe pii_redact eval_gate if_switch http_request csv_table; do
  python -m app.cli.main plugin install "PluginPackage/Common/${p}/" --upgrade
done
python -m app.cli.main plugin install PluginPackage/Audio/dataset_ingest/ --upgrade

python -m app.cli.main run --graph examples/26_nightly_compliance/pipeline.graph.json
```

There is no native Slack node — the live graph stores only the env var **name** (`auth_env`), never the token.
