# app/api/routers/secrets.py
"""REST endpoints for the local named secret store.

GET lists names only. PUT/POST set a value. DELETE removes. Values are never
returned in list/get responses.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.secrets import (
    SecretError,
    delete_secret,
    list_secret_names,
    set_secret,
)

router = APIRouter(prefix="/secrets", tags=["secrets"])


class SecretSetBody(BaseModel):
    name: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


class SecretValueBody(BaseModel):
    value: str = Field(..., min_length=1)


@router.get("", summary="List secret names (values never returned)")
def list_secrets():
    return {"names": list_secret_names()}


@router.post("", summary="Store a named secret")
def create_secret(body: SecretSetBody):
    try:
        name = set_secret(body.name, body.value)
    except SecretError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "name": name}


@router.put("/{name}", summary="Store or replace a named secret")
def put_secret(name: str, body: SecretValueBody):
    try:
        stored = set_secret(name, body.value)
    except SecretError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "name": stored}


@router.delete("/{name}", summary="Delete a named secret")
def remove_secret(name: str):
    try:
        found = delete_secret(name)
    except SecretError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not found:
        raise HTTPException(status_code=404, detail=f"Secret {name!r} not found")
    return {"ok": True, "name": name}
