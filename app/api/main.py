# app/api/main.py
"""
Bounded Context:  REST API Layer
Responsibility:   FastAPI application factory. Wires auth, CORS, routers,
                  static mounts, and domain serializer registration at startup.
Owns:             App instance, auth dependency (_auth_dep), CORS middleware,
                  router inclusion, static file mounts.
Public Surface:   app (FastAPI instance) — imported by uvicorn entry point.
Must NOT:         Contain endpoint logic — all routes live in app/api/routers/.
Dependencies:     fastapi, app.api.routers.*, app.core.config,
                  app.models.audio_artifact_serializer (startup hook).
Reason To Change: New router added, CORS origins change, auth strategy changes,
                  or new startup hook is required.

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

# ── Domain serializer registration ───────────────────────────────────────────
# Register the AudioSampleHandler so that artifact_store, pipeline_cache, and
# checkpoint can serialize/deserialize AudioSample objects without importing
# domain models themselves (ARCH-2 fix).
from app.models.audio_artifact_serializer import register_audio_serializer as _reg_audio
_reg_audio()

# ── Registry initialization ───────────────────────────────────────────────────
# Explicitly populate the NodeRegistry singleton. This must happen after the
# domain serializer is registered (above) so AutoDiscovery can import node
# modules that reference AudioSample without triggering a missing-handler warning.
from app.core.nodes import initialize_registry as _init_registry
try:
    _init_registry()
except Exception as exc:
    _logger.error(
        "Registry initialization failed — server will start with empty/partial registry: %s",
        exc,
        exc_info=True,
    )

# ── Auth ──────────────────────────────────────────────────────────────────────

# Token is intentionally NOT cached at module level.
# Reading on every request ensures:
#   - Token rotation takes effect immediately without a process restart.
#   - Late injection (secrets manager, container orchestrator) works correctly.
_bearer = HTTPBearer(auto_error=False)


def _auth_dep(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
    token = api_token()  # read on every call
    if not token:
        return  # auth not configured — allow all
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != token:
        raise HTTPException(
            status_code=401,
            detail="Invalid Bearer token",
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
    # Enumerate specific headers — allow_headers=["*"] is forbidden by the CORS
    # spec when allow_credentials=True and causes browsers to reject responses.
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Accept"],
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
# NEW-8: Paths are resolved at startup time from GRAPHYN_PROJECT_DIR.
# GRAPHYN_PROJECT_DIR MUST be set before importing this module (e.g. before
# uvicorn loads the app). Setting it after import has no effect on these mounts
# because StaticFiles captures the directory path at mount time.
# In tests, set GRAPHYN_PROJECT_DIR before importing app.api.main.

_OUTPUT_ROOT = datasets_output_dir().resolve()
_INPUT_ROOT  = datasets_input_dir().resolve()
_RUNS_ROOT   = runs_dir().resolve()

_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
_INPUT_ROOT.mkdir(parents=True, exist_ok=True)
_RUNS_ROOT.mkdir(parents=True, exist_ok=True)

_logger.info(
    "Static mounts resolved — /files → %s | /input-files → %s | /run-files → %s",
    _OUTPUT_ROOT,
    _INPUT_ROOT,
    _RUNS_ROOT,
)

app.mount("/files",       StaticFiles(directory=str(_OUTPUT_ROOT)), name="files")
app.mount("/input-files", StaticFiles(directory=str(_INPUT_ROOT)),  name="input-files")
app.mount("/run-files",   StaticFiles(directory=str(_RUNS_ROOT)),   name="run-files")
