# Example 08 — REST API Streaming Pipeline Execution

Demonstrates the REST API as a **real-time monitoring interface** — not just request/response, but a live NDJSON event stream that shows each node executing as it happens.

---

## What This Demonstrates

| Step | Endpoint | What Happens |
|---|---|---|
| 0 | `GET /api/v1/system/health` | Verify the server is running |
| 1 | `GET /api/v1/nodes` | Discover all node types with capability metadata |
| 1b | `GET /api/v1/nodes/{type}` | Inspect a single node's capability fields |
| 2 | `POST /api/v1/pipelines/validate` | Validate IR JSON before running |
| 3 | `POST /api/v1/pipelines/run` | **Stream NDJSON events in real time** |
| 4 | `POST /api/v1/pipelines/run-async` | Fire-and-forget with `run_id` |
| 4b | `GET /api/v1/runs/{run_id}/status` | Poll async run status + progress |
| 4c | `GET /api/v1/runs` | List recent runs |

---

## Prerequisites

Start the API server in a separate terminal:

```bash
venv/bin/uvicorn app.api.main:app --reload --port 8001
```

---

## How to Run

```bash
# Basic streaming demo
venv/bin/python examples/08_rest_api_streaming/stream_client.py

# With verbose output (shows every raw NDJSON event line)
venv/bin/python examples/08_rest_api_streaming/stream_client.py --verbose

# Also run the async run + status polling demo
venv/bin/python examples/08_rest_api_streaming/stream_client.py --async-demo

# Custom server URL
venv/bin/python examples/08_rest_api_streaming/stream_client.py \
    --url http://localhost:8001

# With auth token
GRAPHYN_API_TOKEN=secret \
venv/bin/python examples/08_rest_api_streaming/stream_client.py
```

---

## The Streaming Protocol

`POST /api/v1/pipelines/run` returns `Content-Type: application/x-ndjson` — one JSON object per line, streamed as events occur:

```jsonc
{"type": "pipeline_start", "total_nodes": 6, "timestamp": "2024-01-01T00:00:00+00:00"}
{"type": "node_start",  "node_type": "DatasetIngestNode",    "node_index": 0, "total_nodes": 6, "timestamp": "..."}
{"type": "node_end",    "node_type": "DatasetIngestNode",    "node_index": 0, "duration_s": 0.68, "output_count": 200, "timestamp": "..."}
{"type": "node_start",  "node_type": "AudioConditionerNode", "node_index": 1, "total_nodes": 6, "timestamp": "..."}
{"type": "node_end",    "node_type": "AudioConditionerNode", "node_index": 1, "duration_s": 0.25, "output_count": 200, "timestamp": "..."}
// ... more node events ...
{"type": "done", "timestamp": "..."}
```

All timestamps are UTC ISO 8601 ending in `+00:00`.

---

## IR JSON — The Canonical API Format

The pipeline is submitted as **IR JSON** — the canonical format. The API detects it by the presence of the `schema_version` field:

```json
{
  "schema_version": "1.1",
  "metadata": {"name": "streaming-demo", "seed": 42},
  "nodes": [
    {"id": "dataset_ingest_0",    "node_type": "dataset_ingest",    "config": {"path": "...", "recursive": false, "source_type": "filesystem"}},
    {"id": "audio_conditioner_1", "node_type": "audio_conditioner", "config": {"target_sample_rate": 16000}},
    ...
  ],
  "edges": [
    {"src_id": "dataset_ingest_0", "src_port": "output", "dst_id": "audio_conditioner_1", "dst_port": "input"},
    ...
  ]
}
```

When IR JSON is submitted, the response has **no** `X-Deprecation-Warning` header. When YAML is submitted, the response includes `X-Deprecation-Warning: YAML pipeline input is deprecated.`

---

## Expected Output

```
============================================================
Example 08 — REST API Streaming Execution
============================================================
  API server: http://localhost:8001
  Pipeline: 7 nodes, 6 edges
  Format:   IR JSON (schema_version=1.1)

Step 0 — Health Check
  ✓ Server healthy — status: ok

Step 1 — Node Discovery via REST API
  ✓ 31 node types registered
    Augmentation: 7 nodes
    Export: 5 nodes
    ...
  ✓ audio_conditioner node capability metadata:
    requires_gpu: False
    supports_cpu: True
    ...

Step 2 — Validate Pipeline (IR JSON)
  ✓ No deprecation warning — IR JSON path confirmed
  ✓ Valid — 7 nodes

Step 3 — Streaming Execution (NDJSON)
  ✓ Response Content-Type: application/x-ndjson
  ▶ Pipeline started — 6 nodes
  [████████████████████████████████████████] 6/6  done
  ✓ Pipeline completed in 1.05s

  Node Timing Summary
    DatasetIngestNode    [░░░░░░░░░░░░░░░░░░░░] 0.02s (2%)   200 items
    AudioConditionerNode [░░░░░░░░░░░░░░░░░░░░] 0.03s (2%)   200 items
    SegmenterNode        [░░░░░░░░░░░░░░░░░░░░] 0.03s (2%)   219 items
    AudioQualityGateNode [████████████░░░░░░░░] 0.96s (66%)  219 items
    FeatureFrontendNode  [██░░░░░░░░░░░░░░░░░░] 0.20s (13%)  219 items
    DatasetBuilderNode   [██░░░░░░░░░░░░░░░░░░] 0.22s (15%)  0 items
    DatasetVersionerNode [░░░░░░░░░░░░░░░░░░░░] 0.01s (1%)   0 items
    Total                                       1.47s
```

---

## Building a Progress Display

The `node_index` and `total_nodes` fields in each event let you build a live progress bar:

```python
import httpx, json

with httpx.Client() as client:
    with client.stream("POST", "http://localhost:8001/api/v1/pipelines/run",
                       json=graph) as response:
        for line in response.iter_lines():
            event = json.loads(line)
            if event["type"] == "node_end":
                idx   = event["node_index"]
                total = event.get("total_nodes", 1)
                pct   = (idx + 1) / total * 100
                print(f"\r[{'█' * int(pct/5):<20}] {pct:.0f}%", end="")
            elif event["type"] == "done":
                print("\nDone!")
                break
```

---

## Async Run Pattern

For long-running pipelines, use `run-async` to get a `run_id` immediately and poll for status:

```python
# Start the run
resp = httpx.post("http://localhost:8001/api/v1/pipelines/run-async", json=graph)
run_id = resp.json()["run_id"]

# Poll until done
while True:
    status = httpx.get(f"http://localhost:8001/api/v1/runs/{run_id}/status").json()
    print(f"Status: {status['status']} ({status.get('progress_pct') or 0:.0f}%)")
    if status["status"] in ("completed", "failed", "cancelled"):
        break
    time.sleep(2)
```
