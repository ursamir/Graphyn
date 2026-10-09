# Example 25 — Doc RAG ingest (no vector DB)

doc_parse_chunk → eval_gate (non-empty chunks) → object_store put (local root)

Sample files live in `examples/25_doc_rag_ingest/data/`; `venv/bin/python scripts/heal_e2e_local_data.py`
links them to `workspace/datasets/input/doc-rag-ingest/`, which is what the graph reads.

## Output

Chunk records under `workspace/artifacts/doc-rag-ingest/store/chunks/`.

## Run

```bash
python -m app.cli.main plugin install PluginPackage/Common/doc_parse_chunk/ --upgrade
python -m app.cli.main plugin install PluginPackage/Common/eval_gate/ --upgrade
python -m app.cli.main plugin install PluginPackage/Common/object_store/ --upgrade

python -m app.cli.main run --graph examples/25_doc_rag_ingest/pipeline.graph.json
```

`pipeline.live.graph.json` is the same local-files path (no hosted providers involved).
Embedding and vector-store nodes are not shipped (the RAG pack is removed), so this example stops at chunk storage.
