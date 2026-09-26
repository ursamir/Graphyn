# MCP Agentic Self-Test Transcript

| Field | Value |
|-------|-------|
| **Date** | 2026-09-26 Asia/Calcutta (IST) |
| **Branch tip** | `e3ff497` |
| **Transport** | Official MCP Python SDK (`mcp==1.27.0`) stdio client → `python -m app.mcp.server` on Server-99 host venv |
| **Live API** | `graphyn-api` on `:8001` (rebuilt this session; `/health` ok). Focused retest: lean `GRAPHYN_HOME` with Common+Agents+RAG query-chain plugins. Auth via `GRAPHYN_API_TOKEN` (redacted). |
| **Calls** | 10 (10 ok / 0 fail) |
| **Scope** | Focused closable failures: `get_node_spec(send_email)` + RAG `tpl-rag-query-fs-faiss-support` materialize+execute |

## Honest outcomes

### Before (tip `022d9644`)
- `get_node_spec(send_email)` → FAIL `Unknown node_type in design catalog: send_email`
- RAG execute → FAIL `RAG graph under lean home (RAG nodes not loaded)` / `Node type 'query_rewrite' is not registered`

### After (this tip)
- `get_node_spec(send_email)` → ok=True status=Existing error=None node_type=send_email source=design_catalog pack=PluginPackage/Common/send_email/
- `materialize_template(tpl-rag-query-fs-faiss-support)` → ok=True status=None error=None node_type=None source=None pack=None
- `execute_pipeline(RAG)` → ok=True status=started error=None node_type=None source=None pack=None
- final `inspect_run` → ok=True status=succeeded error=None node_type=None source=None pack=None

### Notes
- Design catalog now includes `send_email` (N146 Existing Common).
- Lean bootstrap installs RAG query-chain stubs (`query_rewrite`…`citation_attach`); API home already auto-installs full PluginPackage including RAG.
- `mcp==1.27.0` pinned in `setup.py` extras; compose/docs warn against unconstrained `pip install mcp` in API image.
- No FaceRecognition / MCU flash fakes.

## Tool call transcript

### 1. `list_tools` — OK

- **ts:** 2026-09-26T09:25:03.749345+05:30
- **args:**
```json
{}
```
- **outcome:**
```json
{
  "count": 74
}
```

### 2. `get_node_spec` — OK

- **ts:** 2026-09-26T09:25:03.754985+05:30
- **args:**
```json
{
  "node_type": "send_email"
}
```
- **outcome:**
```json
{
  "ok": true,
  "node_type": "send_email",
  "pack": "PluginPackage/Common/send_email/",
  "category": "Output",
  "purpose": "Outbound SMTP email via GRAPHYN_SMTP_* (dry-run capable). Not IMAP/inbox.",
  "status": "Existing",
  "kind": null,
  "inputs": [
    {
      "name": "input",
      "type": "Any optional"
    }
  ],
  "outputs": [
    {
      "name": "output",
      "type": "EmailReceipt"
    }
  ],
  "config": [
    "to:str=",
    "subject:str=Graphyn notification",
    "body_template:str=",
    "from_addr:str=",
    "dry_run:bool=false"
  ],
  "notes": "Uses app.core.smtp_notify.send_email. Dry-run via config.dry_run or GRAPHYN_SMTP_DRY_RUN=1. Needs GRAPHYN_SMTP_HOST/FROM for live send.",
  "optional_dependencies_runtime": "stdlib; GRAPHYN_SMTP_* env",
  "honesty": {},
  "related": null,
  "refinement": null,
  "source": "design_catalog"
}
```

### 3. `list_plugins` — OK

- **ts:** 2026-09-26T09:25:03.763562+05:30
- **args:**
```json
{}
```
- **outcome:**
```json
{
  "plugins": [
    {
      "name": "llm-chat",
      "version": "0.3.0",
      "enabled": true,
      "node_types": [
        "llm_chat"
      ]
    },
    {
      "name": "send-email",
      "version": "0.1.0",
      "enabled": true,
      "node_types": [
        "send_email"
      ]
    },
    {
      "name": "set-map",
      "version": "1.0.0",
      "enabled": true,
      "node_types": [
        "set_map"
      ]
    },
    {
      "name": "python-code",
      "version": "1.0.0",
      "enabled": true,
      "node_types": [
        "python_code"
      ]
    },
    {
      "name": "json-transform",
      "version": "1.0.0",
      "enabled": true,
      "node_types": [
        "json_transform"
      ]
    },
    {
      "name": "query-rewrite",
      "version": "0.1.0",
      "enabled": true,
      "node_types": [
        "query_rewrite"
      ]
    },
    {
      "name": "vector-store-query",
      "version": "0.2.0",
      "enabled": true,
      "node_types": [
        "vector_store_query"
      ]
    },
    {
      "name": "rag-rerank",
      "version": "0.1.0",
      "enabled": true,
      "node_types": [
        "rag_rerank"
      ]
    },
    {
      "name": "contextual-compress",
      "version": "0.1.0",
      "enabled": true,
      "node_types": [
        "contextual_compress"
      ]
    },
    {
      "name": "prompt-assemble",
      "version": "0.1.0",
      "enabled": true,
      "node_types": [
        "prompt_assemble"
      ]
    },
    {
      "name": "rag-generate",
      "version": "0.2.0",
      "enabled": true,
      "node_types": [
        "rag_generate"
      ]
    },
    {
      "name": "citation-attach",
      "version": "0.1.0",
      "enabled": true,
      "node_types": [
        "citation_attach"
      ]
    },
    {
      "name": "agent-selftest-echo",
      "version": "0.1.0",
      "enabled": true,
      "node_types": [
        "agent_selftest_echo"
      ]
    }
  ]
}
```

### 4. `materialize_template` — OK

- **ts:** 2026-09-26T09:25:03.811766+05:30
- **args:**
```json
{
  "template_id": "tpl-rag-query-fs-faiss-support"
}
```
- **outcome:**
```json
{
  "ok": true,
  "template_id": "tpl-rag-query-fs-faiss-support",
  "graph": {
    "schema_version": "1.1",
    "metadata": {
      "name": "tpl-rag-query-fs-faiss-support",
      "seed": 42,
      "description": "Dense RAG query over faiss for support.",
      "created_at": null,
      "tags": [
        "rag",
        "query",
        "faiss"
      ],
      "pack": "RAG",
      "industry": "support",
      "marketplace_id": "tpl-rag-query-fs-faiss-support",
      "status": "proposed",
      "source_example": "marketplace/tpl-rag-query-fs-faiss-support.graph.json"
    },
    "nodes": [
      {
        "id": "n0",
        "node_type": "query_rewrite",
        "config": {},
        "label": "query_rewrite",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n1",
        "node_type": "vector_store_query",
        "config": {
          "backend": "faiss"
        },
        "label": "vector_store_query",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n2",
        "node_type": "rag_rerank",
        "config": {},
        "label": "rag_rerank",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n3",
        "node_type": "contextual_compress",
        "config": {},
        "label": "contextual_compress",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n4",
        "node_type": "prompt_assemble",
        "config": {},
        "label": "prompt_assemble",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n5",
        "node_type": "rag_generate",
        "config": {},
        "label": "rag_generate",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n6",
        "node_type": "citation_attach",
        "config": {},
        "label": "citation_attach",
        "capability_metadata": null,
        "event_trigger": null
      }
    ],
    "edges": [
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n1",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n1",
        "src_port": "output",
        "dst_id": "n2",
        "dst_port": "hits",
        "condition": null
      },
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n2",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n2",
        "src_port": "output",
        "dst_id": "n3",
        "dst_port": "hits",
        "condition": null
      },
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n3",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n4",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n3",
        "src_port": "output",
        "dst_id": "n4",
        "dst_port": "hits",
        "condition": null
      },
      {
        "src_id": "n4",
        "src_port": "output",
        "dst_id": "n5",
        "dst_port": "prompt",
        "condition": null
      },
      {
        "src_id": "n5",
        "src_port": "output",
        "dst_id": "n6",
        "dst_port": "answer",
        "condition": null
      },
      {
        "src_id": "n3",
        "src_port": "output",
        "dst_id": "n6",
        "dst_port": "hits",
        "condition": null
      }
    ],
    "parameters": {}
  }
}
```

### 5. `validate_graph` — OK

- **ts:** 2026-09-26T09:25:03.825204+05:30
- **args:**
```json
{
  "graph": {
    "schema_version": "1.1",
    "metadata": {
      "name": "tpl-rag-query-fs-faiss-support",
      "seed": 42,
      "description": "Dense RAG query over faiss for support.",
      "created_at": null,
      "tags": [
        "rag",
        "query",
        "faiss"
      ],
      "pack": "RAG",
      "industry": "support",
      "marketplace_id": "tpl-rag-query-fs-faiss-support",
      "status": "proposed",
      "source_example": "marketplace/tpl-rag-query-fs-faiss-support.graph.json"
    },
    "nodes": [
      {
        "id": "n0",
        "node_type": "query_rewrite",
        "config": {},
        "label": "query_rewrite",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n1",
        "node_type": "vector_store_query",
        "config": {
          "backend": "faiss"
        },
        "label": "vector_store_query",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n2",
        "node_type": "rag_rerank",
        "config": {},
        "label": "rag_rerank",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n3",
        "node_type": "contextual_compress",
        "config": {},
        "label": "contextual_compress",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n4",
        "node_type": "prompt_assemble",
        "config": {},
        "label": "prompt_assemble",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n5",
        "node_type": "rag_generate",
        "config": {},
        "label": "rag_generate",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n6",
        "node_type": "citation_attach",
        "config": {},
        "label": "citation_attach",
        "capability_metadata": null,
        "event_trigger": null
      }
    ],
    "edges": [
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n1",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n1",
        "src_port": "output",
        "dst_id": "n2",
        "dst_port": "hits",
        "condition": null
      },
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n2",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n2",
        "src_port": "output",
        "dst_id": "n3",
        "dst_port": "hits",
        "condition": null
      },
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n3",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n4",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n3",
        "src_port": "output",
        "dst_id": "n4",
        "dst_port": "hits",
        "condition": null
      },
      {
        "src_id": "n4",
        "src_port": "output",
        "dst_id": "n5",
        "dst_port": "prompt",
        "condition": null
      },
      {
        "src_id": "n5",
        "src_port": "output",
        "dst_id": "n6",
        "dst_port": "answer",
        "condition": null
      },
      {
        "src_id": "n3",
        "src_port": "output",
        "dst_id": "n6",
        "dst_port": "hits",
        "condition": null
      }
    ],
    "parameters": {}
  }
}
```
- **outcome:**
```json
{
  "valid": true,
  "node_count": 7,
  "errors": []
}
```

### 6. `save_pipeline` — OK

- **ts:** 2026-09-26T09:25:03.832086+05:30
- **args:**
```json
{
  "project": "mcp-agentic-selftest",
  "pipeline": "uc-rag-focused",
  "graph": {
    "schema_version": "1.1",
    "metadata": {
      "name": "tpl-rag-query-fs-faiss-support",
      "seed": 42,
      "description": "Dense RAG query over faiss for support.",
      "created_at": null,
      "tags": [
        "rag",
        "query",
        "faiss"
      ],
      "pack": "RAG",
      "industry": "support",
      "marketplace_id": "tpl-rag-query-fs-faiss-support",
      "status": "proposed",
      "source_example": "marketplace/tpl-rag-query-fs-faiss-support.graph.json"
    },
    "nodes": [
      {
        "id": "n0",
        "node_type": "query_rewrite",
        "config": {},
        "label": "query_rewrite",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n1",
        "node_type": "vector_store_query",
        "config": {
          "backend": "faiss"
        },
        "label": "vector_store_query",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n2",
        "node_type": "rag_rerank",
        "config": {},
        "label": "rag_rerank",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n3",
        "node_type": "contextual_compress",
        "config": {},
        "label": "contextual_compress",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n4",
        "node_type": "prompt_assemble",
        "config": {},
        "label": "prompt_assemble",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n5",
        "node_type": "rag_generate",
        "config": {},
        "label": "rag_generate",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n6",
        "node_type": "citation_attach",
        "config": {},
        "label": "citation_attach",
        "capability_metadata": null,
        "event_trigger": null
      }
    ],
    "edges": [
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n1",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n1",
        "src_port": "output",
        "dst_id": "n2",
        "dst_port": "hits",
        "condition": null
      },
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n2",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n2",
        "src_port": "output",
        "dst_id": "n3",
        "dst_port": "hits",
        "condition": null
      },
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n3",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n4",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n3",
        "src_port": "output",
        "dst_id": "n4",
        "dst_port": "hits",
        "condition": null
      },
      {
        "src_id": "n4",
        "src_port": "output",
        "dst_id": "n5",
        "dst_port": "prompt",
        "condition": null
      },
      {
        "src_id": "n5",
        "src_port": "output",
        "dst_id": "n6",
        "dst_port": "answer",
        "condition": null
      },
      {
        "src_id": "n3",
        "src_port": "output",
        "dst_id": "n6",
        "dst_port": "hits",
        "condition": null
      }
    ],
    "parameters": {}
  }
}
```
- **outcome:**
```json
{
  "schema_version": "1.1",
  "metadata": {
    "name": "tpl-rag-query-fs-faiss-support",
    "seed": 42,
    "description": "Dense RAG query over faiss for support.",
    "created_at": null,
    "tags": [
      "rag",
      "query",
      "faiss"
    ],
    "project": "mcp-agentic-selftest",
    "version_tag": null
  },
  "nodes": [
    {
      "id": "n0",
      "node_type": "query_rewrite",
      "config": {},
      "label": "query_rewrite",
      "capability_metadata": null,
      "event_trigger": null,
      "placement": null
    },
    {
      "id": "n1",
      "node_type": "vector_store_query",
      "config": {
        "backend": "faiss"
      },
      "label": "vector_store_query",
      "capability_metadata": null,
      "event_trigger": null,
      "placement": null
    },
    {
      "id": "n2",
      "node_type": "rag_rerank",
      "config": {},
      "label": "rag_rerank",
      "capability_metadata": null,
      "event_trigger": null,
      "placement": null
    },
    {
      "id": "n3",
      "node_type": "contextual_compress",
      "config": {},
      "label": "contextual_compress",
      "capability_metadata": null,
      "event_trigger": null,
      "placement": null
    },
    {
      "id": "n4",
      "node_type": "prompt_assemble",
      "config": {},
      "label": "prompt_assemble",
      "capability_metadata": null,
      "event_trigger": null,
      "placement": null
    },
    {
      "id": "n5",
      "node_type": "rag_generate",
      "config": {},
      "label": "rag_generate",
      "capability_metadata": null,
      "event_trigger": null,
      "placement": null
    },
    {
      "id": "n6",
      "node_type": "citation_attach",
      "config": {},
      "label": "citation_attach",
      "capability_metadata": null,
      "event_trigger": null,
      "placement": null
    }
  ],
  "edges": [
    {
      "src_id": "n0",
      "src_port": "output",
      "dst_id": "n1",
      "dst_port": "query",
      "condition": null
    },
    {
      "src_id": "n1",
      "src_port": "output",
      "dst_id": "n2",
      "dst_port": "hits",
      "condition": null
    },
    {
      "src_id": "n0",
      "src_port": "output",
      "dst_id": "n2",
      "dst_port": "query",
      "condition": null
    },
    {
      "src_id": "n2",
      "src_port": "output",
      "dst_id": "n3",
      "dst_port": "hits",
      "condition": null
    },
    {
      "src_id": "n0",
      "src_port": "output",
      "dst_id": "n3",
      "dst_port": "query",
      "condition": null
    },
    {
      "src_id": "n0",
      "src_port": "output",
      "dst_id": "n4",
      "dst_port": "query",
      "condition": null
    },
    {
      "src_id": "n3",
      "src_port": "output",
      "dst_id": "n4",
      "dst_port": "hits",
      "condition": null
    },
    {
      "src_id": "n4",
      "src_port": "output",
      "dst_id": "n5",
      "dst_port": "prompt",
      "condition": null
    },
    {
      "src_id": "n5",
      "src_port": "output",
      "dst_id": "n6",
      "dst_port": "answer",
      "condition": null
    },
    {
      "src_id": "n3",
      "src_port": "output",
      "dst_id": "n6",
      "dst_port": "hits",
      "condition": null
    }
  ],
  "parameters": {},
  "ui": null,
  "resource_version": "1790394903830630097"
}
```

### 7. `execute_pipeline` — OK

- **ts:** 2026-09-26T09:25:03.845210+05:30
- **args:**
```json
{
  "graph": {
    "schema_version": "1.1",
    "metadata": {
      "name": "tpl-rag-query-fs-faiss-support",
      "seed": 42,
      "description": "Dense RAG query over faiss for support.",
      "created_at": null,
      "tags": [
        "rag",
        "query",
        "faiss"
      ],
      "pack": "RAG",
      "industry": "support",
      "marketplace_id": "tpl-rag-query-fs-faiss-support",
      "status": "proposed",
      "source_example": "marketplace/tpl-rag-query-fs-faiss-support.graph.json"
    },
    "nodes": [
      {
        "id": "n0",
        "node_type": "query_rewrite",
        "config": {},
        "label": "query_rewrite",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n1",
        "node_type": "vector_store_query",
        "config": {
          "backend": "faiss"
        },
        "label": "vector_store_query",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n2",
        "node_type": "rag_rerank",
        "config": {},
        "label": "rag_rerank",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n3",
        "node_type": "contextual_compress",
        "config": {},
        "label": "contextual_compress",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n4",
        "node_type": "prompt_assemble",
        "config": {},
        "label": "prompt_assemble",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n5",
        "node_type": "rag_generate",
        "config": {},
        "label": "rag_generate",
        "capability_metadata": null,
        "event_trigger": null
      },
      {
        "id": "n6",
        "node_type": "citation_attach",
        "config": {},
        "label": "citation_attach",
        "capability_metadata": null,
        "event_trigger": null
      }
    ],
    "edges": [
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n1",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n1",
        "src_port": "output",
        "dst_id": "n2",
        "dst_port": "hits",
        "condition": null
      },
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n2",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n2",
        "src_port": "output",
        "dst_id": "n3",
        "dst_port": "hits",
        "condition": null
      },
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n3",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n0",
        "src_port": "output",
        "dst_id": "n4",
        "dst_port": "query",
        "condition": null
      },
      {
        "src_id": "n3",
        "src_port": "output",
        "dst_id": "n4",
        "dst_port": "hits",
        "condition": null
      },
      {
        "src_id": "n4",
        "src_port": "output",
        "dst_id": "n5",
        "dst_port": "prompt",
        "condition": null
      },
      {
        "src_id": "n5",
        "src_port": "output",
        "dst_id": "n6",
        "dst_port": "answer",
        "condition": null
      },
      {
        "src_id": "n3",
        "src_port": "output",
        "dst_id": "n6",
        "dst_port": "hits",
        "condition": null
      }
    ],
    "parameters": {}
  },
  "use_cache": false
}
```
- **outcome:**
```json
{
  "run_id": "5a41469965d7415d8e8200d2b4591959",
  "status": "started"
}
```

### 8. `inspect_run` — OK

- **ts:** 2026-09-26T09:25:03.856414+05:30
- **args:**
```json
{
  "run_id": "5a41469965d7415d8e8200d2b4591959",
  "status_only": true
}
```
- **outcome:**
```json
{
  "status": "pending"
}
```

### 9. `inspect_run` — OK

- **ts:** 2026-09-26T09:25:04.863790+05:30
- **args:**
```json
{
  "run_id": "5a41469965d7415d8e8200d2b4591959",
  "status_only": true
}
```
- **outcome:**
```json
{
  "status": "succeeded"
}
```

### 10. `inspect_run` — OK

- **ts:** 2026-09-26T09:25:04.868140+05:30
- **args:**
```json
{
  "run_id": "5a41469965d7415d8e8200d2b4591959"
}
```
- **outcome:**
```json
{
  "run_id": "5a41469965d7415d8e8200d2b4591959",
  "created_at": "2026-09-26T03:55:03.838690+00:00",
  "status": "succeeded",
  "artifacts_dir": "workspace/artifacts/tpl-rag-query-fs-faiss-support/runs/5a41469965d7415d8e8200d2b4591959",
  "graph_hash": "4c3b4e81cc085a9ef0fac44ba65433160ed052b40d1b86af3aef431e61d766dc",
  "graph_name": "tpl-rag-query-fs-faiss-support",
  "num_nodes": 7,
  "node_stats": [
    {
      "node_id": "n0",
      "node_type": "query_rewrite",
      "node_index": 0,
      "duration_s": 0.0035,
      "duration_ms": 3.52,
      "status": "completed",
      "cache_hit": false
    },
    {
      "node_id": "n1",
      "node_type": "vector_store_query",
      "node_index": 1,
      "duration_s": 0.1203,
      "duration_ms": 120.28,
      "status": "completed",
      "cache_hit": false
    },
    {
      "node_id": "n2",
      "node_type": "rag_rerank",
      "node_index": 2,
      "duration_s": 0.0005,
      "duration_ms": 0.51,
      "status": "completed",
      "cache_hit": false
    },
    {
      "node_id": "n3",
      "node_type": "contextual_compress",
      "node_index": 3,
      "duration_s": 0.0004,
      "duration_ms": 0.45,
      "status": "completed",
      "cache_hit": false
    },
    {
      "node_id": "n4",
      "node_type": "prompt_assemble",
      "node_index": 4,
      "duration_s": 0.0008,
      "duration_ms": 0.78,
      "status": "completed",
      "cache_hit": false
    },
    {
      "node_id": "n5",
      "node_type": "rag_generate",
      "node_index": 5,
      "duration_s": 0.0009,
      "duration_ms": 0.85,
      "status": "completed",
      "cache_hit": false
    },
    {
      "node_id": "n6",
      "node_type": "citation_attach",
      "node_index": 6,
      "duration_s": 0.0008,
      "duration_ms": 0.76,
      "status": "completed",
      "cache_hit": false
    }
  ],
  "duration_s": 0.1289
}
```

