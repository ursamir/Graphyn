# Example 27 — Issue triage

ingest voice notes → asr → pii → structured_llm (severity, summary, labels) → if_switch on severity → queue / backlog

| Graph | Providers | Output | Needs |
|---|---|---|---|
| `pipeline.graph.json` | local Whisper (`tiny`), rule-based extract (`rule_based`) | `workspace/artifacts/github-triage/queue.csv` (severity set) and `backlog.csv` (otherwise) | nothing — runs offline |
| `pipeline.live.graph.json` | OpenAI-compatible ASR + LLM, GitHub REST via `http_request` + `auth_env=GITHUB_TOKEN` | issue list + comment on the issue | `OPENAI_API_KEY`, `GITHUB_TOKEN`, your repo URLs |

There is no native GitHub node; the live graph stores only the env var **name**. Edit the
`api.github.com/repos/example/app/...` URLs before running it.

```bash
for p in http_request asr_transcribe pii_redact structured_llm if_switch csv_table; do
  python -m app.cli.main plugin install "PluginPackage/Common/${p}/" --upgrade
done
python -m app.cli.main plugin install PluginPackage/Audio/dataset_ingest/ --upgrade
python -m app.cli.main run --graph examples/27_github_triage/pipeline.graph.json
```
