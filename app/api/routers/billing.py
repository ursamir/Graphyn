# app/api/routers/billing.py
"""Billing webhook seam (HMAC) — records deliveries for metering / Stripe-style hooks."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

public_router = APIRouter(tags=["billing"])


@public_router.post("/billing/webhook", summary="Inbound billing provider webhook (HMAC)")
async def billing_webhook(request: Request):
    """Accepts Stripe-style signed webhooks when GRAPHYN_BILLING_WEBHOOK_SECRET is set.

    Does not charge cards — records the delivery and optional meter events from
    ``{"type": "...", "data": {"object": {"metadata": {"org_id": "..."}}}}``.
    """
    from app.core.trust.metering import get_meter_store, record_meter_event, verify_billing_webhook_signature

    raw = await request.body()
    sig = request.headers.get("Stripe-Signature") or request.headers.get("X-Graphyn-Signature")
    # Stripe sends multiple kv pairs; accept also raw sha256=
    if sig and "v1=" in sig:
        # Take first v1=… fragment as HMAC hex and wrap as sha256=
        for part in sig.split(","):
            part = part.strip()
            if part.startswith("v1="):
                sig = "sha256=" + part[3:]
                break
    ok = verify_billing_webhook_signature(raw, sig)
    store = get_meter_store()
    if not ok:
        store.record_webhook_delivery(None, raw, "rejected", "bad_signature_or_secret_unset")
        raise HTTPException(status_code=401, detail="Invalid billing webhook signature")
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    event_type = str(payload.get("type") or payload.get("event_type") or "billing.event")
    wid = store.record_webhook_delivery(event_type, raw, "accepted")
    org_id = None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    obj = data.get("object") if isinstance(data.get("object"), dict) else {}
    meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    org_id = meta.get("org_id") or payload.get("org_id")
    if org_id:
        record_meter_event(
            str(org_id),
            f"billing.{event_type}",
            actor="billing_webhook",
            resource_type="billing",
            resource_id=wid,
            meta={"webhook_id": wid},
        )
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor="billing_webhook",
            action="billing.webhook",
            resource_type="billing",
            resource_id=wid,
            actor_kind="billing_webhook",
            meta={"event_type": event_type, "org_id": org_id},
        )
    except Exception:
        pass
    return {"ok": True, "id": wid, "event_type": event_type}


# Authenticated admin metering status (no payment UI)
router = APIRouter(tags=["billing"])


@router.get("/billing/status", summary="Billing webhook + metering honesty status")
def billing_status():
    from app.core.trust.identity import current_identity
    from app.core.trust.rbac import permissions_for
    from app.core.trust.metering import get_meter_store

    ident = current_identity() or {}
    if ident.get("kind") == "user":
        perms = permissions_for(ident.get("roles") or [])
        if "users.admin" not in perms and "admin" not in perms and "system.admin" not in perms:
            raise HTTPException(status_code=403, detail="Billing status requires admin")
    return get_meter_store().billing_webhook_status()
