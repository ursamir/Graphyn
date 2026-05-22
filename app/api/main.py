# app/api/main.py
"""Graphyn API — thin app factory.

All endpoint logic lives in routers under app/api/routers/.
All routes are served under /api/v1/.
No legacy root-path endpoints.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from app.api.routers.nodes import router as nodes_router
from app.api.routers.pipelines import router as pipelines_router
from app.api.routers.runs import router as runs_router
from app.api.routers.data import router as data_router
from app.api.routers.system import router as system_router
from app.api.routers.projects import router as projects_router
from app.api.routers.ingest import router as ingest_router
from app.api.routers.run_control import router as run_control_router
from app.api.routers.artifacts import router as artifacts_router
from app.api.routers.plugins import router as plugins_router
from app.core.config import api_token, datasets_output_dir, datasets_input_dir, runs_dir

_logger = logging.getLogger(__name__)

# ── Auth ──────────────────────────────────────────────────────────────────────

_API_TOKEN = api_token()
if not _API_TOKEN:
    _logger.warning(
        "GRAPHYN_API_TOKEN is not set — running without authentication."
    )

_bearer = HTTPBearer(auto_error=False)


def _auth_dep(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
    if not _API_TOKEN:
        return  # auth not configured — allow all
    if credentials is None or credentials.credentials != _API_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(title="Graphyn API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "DELETE", "PUT", "PATCH"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

_deps = [Depends(_auth_dep)]

app.include_router(nodes_router,       prefix="/api/v1", dependencies=_deps)
app.include_router(pipelines_router,   prefix="/api/v1", dependencies=_deps)
app.include_router(runs_router,        prefix="/api/v1", dependencies=_deps)
app.include_router(data_router,        prefix="/api/v1", dependencies=_deps)
app.include_router(system_router,      prefix="/api/v1", dependencies=_deps)
app.include_router(projects_router,    prefix="/api/v1", dependencies=_deps)
app.include_router(ingest_router,      prefix="/api/v1", dependencies=_deps)
app.include_router(run_control_router, prefix="/api/v1", dependencies=_deps)
app.include_router(artifacts_router,   prefix="/api/v1", dependencies=_deps)
app.include_router(plugins_router,     prefix="/api/v1", dependencies=_deps)

# ── Static file mounts ────────────────────────────────────────────────────────
# Paths are resolved from GRAPHYN_PROJECT_DIR.

_OUTPUT_ROOT = datasets_output_dir().resolve()
_INPUT_ROOT  = datasets_input_dir().resolve()
_RUNS_ROOT   = runs_dir().resolve()

_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
_INPUT_ROOT.mkdir(parents=True, exist_ok=True)
_RUNS_ROOT.mkdir(parents=True, exist_ok=True)

app.mount("/files",       StaticFiles(directory=str(_OUTPUT_ROOT)), name="files")
app.mount("/input-files", StaticFiles(directory=str(_INPUT_ROOT)),  name="input-files")
app.mount("/run-files",   StaticFiles(directory=str(_RUNS_ROOT)),   name="run-files")
