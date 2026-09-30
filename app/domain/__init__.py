# app/domain/__init__.py
"""
Bounded Context:  Domain
Responsibility:   Domain services for ingestion, projects, and dataset quality.
Owns:             Nothing at import time. Import the service module you need.
Public Surface:   app.domain.project_manager, app.domain.ingestion, app.domain.quality_checker
Must NOT:         Be imported by app.core storage or the execution kernel.
Dependencies:     None at package import.
Reason To Change: A domain service is added or renamed.
"""
