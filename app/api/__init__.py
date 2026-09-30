# app/api/__init__.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP package marker. Routers and the app factory live in submodules.
Owns:             Nothing at import time.
Public Surface:   app.api.main:app, app.api.routers
Must NOT:         Import FastAPI, routers, or the plugin registry here.
Dependencies:     None.
Reason To Change: The API package's import boundary changes.
"""
