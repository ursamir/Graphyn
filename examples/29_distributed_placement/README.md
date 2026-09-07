# 29 — Distributed placement (two-box / Server-99)

Schema-valid Common-node demo: local `python_code` → remote `set_map` with
`placement.tags=["gpu"]` / `require_gpu=true` → local `json_transform` sink.

Ports are `input`/`output` throughout (unlike trainer/evaluator which need
`model`/`dataset` wiring).

See [docs/DISTRIBUTED_EXECUTION.md](../../docs/DISTRIBUTED_EXECUTION.md)
Server-99 two-box runbook (includes an optional trainer-oriented sketch).
