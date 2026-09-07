# app/core/egress.py
"""
Bounded Context:  Platform Infrastructure (shared by all BCs)
Responsibility:   HTTP egress policy for workflow nodes (SSRF hardening).
Owns:             HttpEgressError, validate_http_egress_url(), is_blocked_ip(),
                  host_on_allowlist().
Public Surface:   validate_http_egress_url(url) -> None (raises on deny)
Must NOT:         Perform the HTTP request itself; only validate destinations.
                  Must not cache env reads at import time (token/mode rotation).
Dependencies:     stdlib (ipaddress, socket, urllib.parse), app.core.config.
Reason To Change: Egress policy expands (pin-IP connect, IPv6 getaddrinfo),
                  or additional callers (ASR/LLM providers) opt in.

Trust model (Option A): default GRAPHYN_HTTP_EGRESS_MODE=trusted preserves
current behaviour for single-tenant / shared-bearer deployments. Restricted
mode is defense for multi-tenant or untrusted graph authors — not a full
network sandbox.

Limitations: validation resolves DNS once at check time; the subsequent HTTP
client may resolve again (DNS rebinding TOCTOU). Pinning the connection to the
validated IP (as WebhookService does) is not yet applied to http_request /
http_webhook. CNAME chains and dual-stack AAAA-only private answers depend on
getaddrinfo coverage.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from app.core.config import http_egress_allowlist, http_egress_mode

log = logging.getLogger(__name__)

_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Hostnames commonly used for cloud instance metadata (blocked in restricted).
_METADATA_HOSTS = frozenset({
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
    "instance-data",
})


class HttpEgressError(RuntimeError):
    """Raised when a workflow HTTP destination is denied by egress policy."""


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for private, loopback, link-local, ULA, reserved, multicast, unspecified."""
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def host_on_allowlist(hostname: str, allowlist: list[str] | None = None) -> bool:
    """True when *hostname* exactly matches or is a subdomain of an allowlist entry.

    Allowlist entries may be bare hostnames/domains or URLs (hostname extracted).
    Empty allowlist → False (caller decides whether empty means "no filter").
    """
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    entries = allowlist if allowlist is not None else http_egress_allowlist()
    if not entries:
        return False
    for entry in entries:
        raw = (entry or "").strip().lower()
        if not raw:
            continue
        if "://" in raw:
            parsed = urlparse(raw)
            candidate = (parsed.hostname or "").lower().rstrip(".")
        else:
            candidate = raw.split("/")[0].split(":")[0].rstrip(".")
        if not candidate:
            continue
        if host == candidate or host.endswith("." + candidate):
            return True
    return False


def _resolve_ips(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve *hostname* via getaddrinfo (IPv4 + IPv6 when available)."""
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HttpEgressError(
            f"HTTP egress: hostname {hostname!r} could not be resolved: {exc}"
        ) from exc

    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        addr = sockaddr[0]
        if "%" in addr:
            addr = addr.split("%", 1)[0]
        if addr in seen:
            continue
        seen.add(addr)
        try:
            ips.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    if not ips:
        raise HttpEgressError(
            f"HTTP egress: hostname {hostname!r} resolved to no usable addresses."
        )
    return ips


def validate_http_egress_url(url: str, *, mode: str | None = None) -> None:
    """Validate *url* against the configured HTTP egress policy.

    In ``trusted`` mode this is a no-op (aside from requiring a non-empty URL
    when callers pass one). In ``restricted`` mode:

    - Only ``http`` / ``https`` schemes
    - Hostname required
    - Known cloud-metadata hostnames blocked
    - Optional host allowlist (when ``GRAPHYN_HTTP_EGRESS_ALLOWLIST`` is set)
    - All resolved IPs must be public (not RFC1918 / link-local / loopback /
      ULA / reserved / multicast / unspecified), including ``169.254.169.254``

    Raises:
        HttpEgressError: when the destination is denied.
    """
    url = (url or "").strip()
    if not url:
        raise HttpEgressError("HTTP egress: URL is required.")

    effective = (mode or http_egress_mode()).lower()
    if effective == "trusted":
        return
    if effective != "restricted":
        raise HttpEgressError(
            f"HTTP egress: unknown mode {effective!r}; use trusted|restricted."
        )

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise HttpEgressError(
            f"HTTP egress: scheme {scheme!r} is not allowed in restricted mode "
            f"(use http or https). URL={url!r}"
        )
    hostname = parsed.hostname
    if not hostname:
        raise HttpEgressError(f"HTTP egress: URL must include a hostname. URL={url!r}")

    host_l = hostname.lower().rstrip(".")
    if host_l in _METADATA_HOSTS:
        raise HttpEgressError(
            f"HTTP egress: metadata host {hostname!r} is blocked in restricted mode."
        )

    allowlist = http_egress_allowlist()
    if allowlist and not host_on_allowlist(host_l, allowlist):
        raise HttpEgressError(
            f"HTTP egress: host {hostname!r} is not on GRAPHYN_HTTP_EGRESS_ALLOWLIST."
        )

    for ip in _resolve_ips(hostname):
        if is_blocked_ip(ip):
            raise HttpEgressError(
                f"HTTP egress: {hostname!r} resolves to blocked address {ip} "
                "(private/link-local/loopback/reserved). Restricted mode denies "
                "SSRF-prone destinations."
            )
