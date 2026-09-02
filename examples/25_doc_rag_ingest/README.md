# Example 25 — Doc RAG ingest (no vector DB)

doc_parse_chunk → eval_gate (non-empty chunks) → object_store put (local root)

Sample files live in `examples/25_doc_rag_ingest/data/`.

## Output

Markdown chunk files under `examples/25_doc_rag_ingest/output/store/chunks/`.

## Run

```bash
python -m app.cli.main plugin install PluginPackage/Common/doc_parse_chunk/ --upgrade
python -m app.cli.main plugin install PluginPackage/Common/eval_gate/ --upgrade
python -m app.cli.main plugin install PluginPackage/Common/object_store/ --upgrade

python -m app.cli.main run --graph examples/25_doc_rag_ingest/pipeline.graph.json
```

## Live vs mock

`pipeline.live.graph.json` is the same local-files path (no cloud providers).
