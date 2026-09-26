# Mode B operate ? control DESKTOP-001, worker Server-99

| Field | Value |
|-------|-------|
| **Date** | 2026-09-26 (Asia/Calcutta) |
| **Control plane** | DESKTOP-001 `192.168.0.153` (bot box cannot reach LAN `192.168.0.170`) |
| **Worker** | Server-99 `192.168.0.170` (`meritech@server99`) |
| **Auth** | shared Bearer `GRAPHYN_API_TOKEN` (smoke used `mode-b-local-token`) |
| **Transport** | SSH reverse tunnel `ssh -N -R 18001:127.0.0.1:18001 server99` |

## Why not bot box as control?

Agent box (`172.30.0.2`) times out to `192.168.0.170`. Prefer DESKTOP-001 on the LAN, or tunnel.

## Topology

```
DESKTOP-001 (control)                 Server-99 (worker)
  uvicorn :18001  GRAPHYN_BACKEND=distributed
       ^                                      |
       +---- ssh -R 18001:127.0.0.1:18001 -----+
            worker uses http://127.0.0.1:18001/api/v1
```

## Ops steps (summary)

1. Control: `GRAPHYN_BACKEND=distributed GRAPHYN_API_TOKEN=? uvicorn app.api.main:app --host 127.0.0.1 --port 18001`
2. Tunnel: `ssh -N -R 18001:127.0.0.1:18001 server99`
3. Worker (lean plugins only ? avoid filling disk with isolated venvs):
   `GRAPHYN_AUTO_INSTALL_PLUGINS=0 GRAPHYN_HOME=?/.graphyn-modeb-worker`
   install `python_code`/`set_map`/`json_transform` only, then
   `python -m app.cli.main worker start --control-url http://127.0.0.1:18001/api/v1 --worker-id server99-gpu --labels gpu,lab --pool gpu-lab --plugins set_map,python_code,json_transform`
4. Run: `GRAPHYN_BACKEND=distributed python -m app.cli.main run --graph examples/29_distributed_placement/pipeline.graph.json`

## Hardening included this wave

- `queue.py`: `_plain_jsonable` before durable `model_dump` (mappingproxy / IR configs)
- `isolated_executor.recast_plugin_types`: cross-host fallback to plain dict when no platform type
- Worker complete events: recast outputs before JSON report (MappedPayload)

## Smoke table (2026-09-26 IST)

| Check | Result |
|-------|--------|
| Control `GET /system/health` :18001 | ok |
| Tunnel from S99 ? control | ok |
| `GET /workers` includes `server99-gpu` | ok (labels gpu,lab; pool gpu-lab) |
| Demo run `examples/29_distributed_placement` | **exit 0**; `gpu_step` status=succeeded, `worker_id=server99-gpu` |
| Disk note | Do **not** auto-install full PluginPackage into worker home (filled ~38GB once); keep lean |

## Unit tests

```bash
GRAPHYN_SKIP_PLUGIN_LOAD=1 GRAPHYN_DISTRIBUTED_STORE=memory \
  pytest unit_test/core/test_distributed_*.py -q --tb=line
```

## Refs

- docs/DISTRIBUTED_EXECUTION.md ?14
- docs/GETTING_STARTED.md Mode B
- examples/29_distributed_placement/
