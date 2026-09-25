# app/mcp/handlers/ship_ops.py
"""MCP tools for ship packages (J4) — wrap app.core.ship_packages."""
from __future__ import annotations

from typing import Any


def _err(error_type: str, message: str) -> dict[str, Any]:
    return {"error": True, "error_type": error_type, "message": message}


def _require_project_dir(project: str):
    from app.domain.project_manager import ProjectManager

    name = (project or "").strip()
    if not name:
        raise ValueError("project is required")
    return ProjectManager()._require_project(name), name


def _meta_props() -> dict[str, Any]:
    return {
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        }
    }


LIST_SHIP_PACKAGES_DESCRIPTION = "List ship packages for a project workspace."
LIST_SHIP_PACKAGES_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "limit": {"type": "integer"},
        "env": {"type": "string"},
        **_meta_props(),
    },
    "required": ["project"],
    "additionalProperties": False,
}

GET_SHIP_PACKAGE_DESCRIPTION = "Get a ship package manifest and status by id."
GET_SHIP_PACKAGE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "package_id": {"type": "string"},
        **_meta_props(),
    },
    "required": ["project", "package_id"],
    "additionalProperties": False,
}

CREATE_SHIP_PACKAGE_DESCRIPTION = (
    "Create a ship package from a registered model (writes manifest + archive)."
)
CREATE_SHIP_PACKAGE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "model_name": {"type": "string"},
        "model_stage_or_version": {"type": "string"},
        "target": {"type": "object"},
        "env": {"type": "string"},
        "notes": {"type": "string"},
        "unsigned_allowed": {"type": "boolean"},
        "actor": {"type": "string"},
        **_meta_props(),
    },
    "required": ["project", "model_name", "model_stage_or_version", "target"],
    "additionalProperties": False,
}

DOWNLOAD_SHIP_PACKAGE_DESCRIPTION = (
    "Return ship package download descriptors (path + checksums). "
    "Does not stream binary over MCP."
)
DOWNLOAD_SHIP_PACKAGE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "package_id": {"type": "string"},
        **_meta_props(),
    },
    "required": ["project", "package_id"],
    "additionalProperties": False,
}

PROMOTE_SHIP_PACKAGE_DESCRIPTION = (
    "Promote a ship package channel to staging/prod (prod requires approve=true)."
)
PROMOTE_SHIP_PACKAGE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "package_id": {"type": "string"},
        "to_env": {"type": "string"},
        "approve": {"type": "boolean"},
        "actor": {"type": "string"},
        **_meta_props(),
    },
    "required": ["project", "package_id", "to_env"],
    "additionalProperties": False,
}


def list_ship_packages_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.ship_packages import list_packages

    args = arguments or {}
    try:
        project_dir, _ = _require_project_dir(str(args.get("project") or ""))
        return list_packages(
            project_dir,
            limit=int(args.get("limit") or 100),
            env=args.get("env"),
        )
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def get_ship_package_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.ship_packages import get_package

    args = arguments or {}
    try:
        project_dir, _ = _require_project_dir(str(args.get("project") or ""))
        return get_package(project_dir, str(args.get("package_id") or "").strip())
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def create_ship_package_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.ship_packages import InvalidPackageTransition, create_package

    args = arguments or {}
    target = args.get("target")
    if not isinstance(target, dict):
        return _err("validation_failed", "target object required")
    try:
        project_dir, name = _require_project_dir(str(args.get("project") or ""))
        return create_package(
            project_dir,
            project_name=name,
            model_name=str(args.get("model_name") or "").strip(),
            model_stage_or_version=str(args.get("model_stage_or_version") or "").strip(),
            target=target,
            env=str(args.get("env") or "draft"),
            actor=str(args.get("actor") or "mcp"),
            notes=args.get("notes"),
            unsigned_allowed=bool(
                args.get("unsigned_allowed")
                if args.get("unsigned_allowed") is not None
                else True
            ),
        )
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except InvalidPackageTransition as exc:
        return _err("invalid_transition", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def download_ship_package_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.ship_packages import download_package_path

    args = arguments or {}
    try:
        project_dir, name = _require_project_dir(str(args.get("project") or ""))
        package_id = str(args.get("package_id") or "").strip()
        archive, man = download_package_path(project_dir, package_id)
        checksums = man.get("checksums") if isinstance(man.get("checksums"), dict) else {}
        return {
            "package_id": package_id,
            "project": name,
            "path": str(archive),
            "download_url": f"/api/v1/projects/{name}/ship/packages/{package_id}/download",
            "checksums": checksums,
            "status": man.get("status"),
            "size": archive.stat().st_size if archive.is_file() else None,
        }
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("conflict", str(exc))


def promote_ship_package_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.ship_packages import InvalidPackageTransition, promote_package

    args = arguments or {}
    try:
        project_dir, _ = _require_project_dir(str(args.get("project") or ""))
        return promote_package(
            project_dir,
            str(args.get("package_id") or "").strip(),
            to_env=str(args.get("to_env") or "").strip(),
            approve=bool(args.get("approve")),
            actor=str(args.get("actor") or "mcp"),
        )
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except InvalidPackageTransition as exc:
        return _err("invalid_transition", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))
