# Example 27 — GitHub triage

http_request (mock GitHub issues, `auth_env=GITHUB_TOKEN`) plus ingest → asr → pii → structured_llm → if_switch → http_request (mock comment).

No native GitHub node in v1. Put the token in the environment; the IR only stores the **variable name**.

```bash
for p in http_request asr_transcribe pii_redact structured_llm if_switch; do
  python -m app.cli.main plugin install "PluginPackage/Common/${p}/" --upgrade
done
python -m app.cli.main plugin install PluginPackage/Audio/dataset_ingest/ --upgrade
python -m app.cli.main run --graph examples/27_github_triage/pipeline.graph.json
```
