# app/core/credentials/inbound_webhook.py
"""
Bounded Context:  BC6 — Observability & Storage (credentials)
Responsibility:   Register the ``inbound_webhook`` credential kind: the HMAC
                  signing secret of one pipeline's inbound webhook
                  (POST /api/v1/hooks/{workspace}/{pipeline}).
Owns:             INBOUND_WEBHOOK_KIND, ensure_inbound_webhook_kind().
Public Surface:   ensure_inbound_webhook_kind() (idempotent; runs on import).
Must NOT:         Import app.api / app.domain; log secret values.
Dependencies:     app.core.credentials.kinds.
Reason To Change: Inbound webhook secret fields change.

Kept in its own module (append-only registration) so kinds.py stays owned by
the built-in kind list.
"""
from __future__ import annotations

from app.core.credentials.kinds import CredentialKind, KindField, get_kind, register_kind

INBOUND_WEBHOOK_KIND = "inbound_webhook"


def ensure_inbound_webhook_kind() -> None:
    """Register ``inbound_webhook`` once (no-op when already registered)."""
    if get_kind(INBOUND_WEBHOOK_KIND) is not None:
        return
    register_kind(CredentialKind(
        id=INBOUND_WEBHOOK_KIND,
        label="Inbound webhook secret",
        description=(
            "HMAC-SHA256 signing secret for one pipeline's inbound webhook. "
            "Created / rotated by POST /projects/{ws}/pipelines/{p}/hook/rotate."
        ),
        fields=[
            KindField("secret", secret=True, required=True, description="HMAC signing secret"),
            KindField("workspace", secret=False, required=False, description="Workspace", default=""),
            KindField("pipeline", secret=False, required=False, description="Pipeline", default=""),
        ],
        env_fallbacks={},
    ))


ensure_inbound_webhook_kind()
