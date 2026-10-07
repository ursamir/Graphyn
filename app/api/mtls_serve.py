# app/api/mtls_serve.py
"""Uvicorn entrypoint with optional Mode B mTLS (mutual TLS).

Bounded Context:  BC5 Execution Runtime (Mode B control-plane transport).
Responsibility:   Start the API under uvicorn; when GRAPHYN_MTLS_ENABLED=1,
                  serve TLS with required client certs and expose the peer
                  cert to the identity middleware.
Owns:             main().
Public Surface:   ``python -m app.api.mtls_serve``.
Must NOT:         Fall back to plain HTTP when mTLS is enabled; use a uvicorn
                  HTTP protocol whose transport the peercert patch does not
                  cover (pinned to ``h11``).
Dependencies:     uvicorn, app.core.distributed.mtls.
Reason To Change: TLS/listener configuration for the control plane.

Env (when GRAPHYN_MTLS_ENABLED=1)::

    GRAPHYN_MTLS_CA_CERT   CA PEM
    GRAPHYN_MTLS_CERT      control server cert PEM
    GRAPHYN_MTLS_KEY       control server key PEM

HTTP (no TLS) remains the default when mTLS is disabled — lab without certs.
"""
from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    from app.core.distributed.mtls import (
        install_uvicorn_peercert_patch,
        mtls_enabled,
        uvicorn_ssl_kwargs,
    )

    host = (os.environ.get("GRAPHYN_API_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    try:
        port = int(os.environ.get("GRAPHYN_API_PORT") or "8001")
    except ValueError:
        port = 8001

    ssl_kwargs: dict = {}
    if mtls_enabled():
        install_uvicorn_peercert_patch()
        ssl_kwargs = uvicorn_ssl_kwargs()
        print(
            f"graphyn-api: mTLS ENABLED on {host}:{port} "
            f"(ca={ssl_kwargs.get('ssl_ca_certs')})",
            flush=True,
            file=sys.stderr,
        )
    else:
        print(
            f"graphyn-api: plain HTTP on {host}:{port} (mTLS disabled)",
            flush=True,
            file=sys.stderr,
        )

    uvicorn.run(
        "app.api.main:app",
        host=host,
        port=port,
        # The peercert patch hooks H11Protocol only; httptools would leave
        # every request without a cert identity.
        **({"http": "h11"} if ssl_kwargs else {}),
        **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
