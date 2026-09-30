# app/api/routers/__init__.py
"""
Bounded Context:  REST API Layer
Responsibility:   One router module per HTTP resource.
Owns:             Nothing at import time. Each module owns its APIRouter.
Public Surface:   app.api.routers.<resource>.router
Must NOT:         Import every router here — app.api.main mounts them.
Dependencies:     None.
Reason To Change: A router module is added or renamed.
"""
