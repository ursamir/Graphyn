---
inclusion: fileMatch
fileMatchPattern: "app/api/main.py"
---

# API Structure

`app/api/main.py` is a thin factory. No endpoint logic here.

## Auth

```python
_API_TOKEN = api_token()  # reads GRAPHYN_API_TOKEN
```

When set: all `/api/v1/` requests require `Authorization: Bearer <token>`. When unset: all allowed.

## CORS Origins

`http://localhost:3000`, `http://127.0.0.1:3000`, `http://localhost:5173`, `http://127.0.0.1:5173`

Allowed headers: `Authorization`, `Content-Type`, `X-Request-ID`, `Accept`

## Active Routers

| Router | Prefix | File |
|---|---|---|
| `nodes_router` | `/api/v1` | `routers/nodes.py` |
| `pipelines_router` | `/api/v1` | `routers/pipelines.py` |
| `runs_router` | `/api/v1` | `routers/runs.py` |
| `run_control_router` | `/api/v1` | `routers/run_control.py` |
| `data_router` | `/api/v1` | `routers/data.py` |
| `system_router` | `/api/v1` | `routers/system.py` |
| `projects_router` | `/api/v1` | `routers/projects.py` |
| `ingest_router` | `/api/v1` | `routers/ingest.py` |
| `artifacts_router` | `/api/v1` | `routers/artifacts.py` |
| `plugins_router` | `/api/v1` | `routers/plugins.py` |

## Static Mounts

| Mount | Filesystem |
|---|---|
| `/files/` | `workspace/datasets/output/` |
| `/input-files/` | `workspace/datasets/input/` |
| `/run-files/` | `workspace/runs/` |

## Adding a Router

1. Create `app/api/routers/my_router.py` with `router = APIRouter()`
2. Import and `app.include_router(my_router, prefix="/api/v1", dependencies=_deps)`
3. Add row to Active Routers table above and to `api-endpoints.md`


