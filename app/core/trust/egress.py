# app/core/trust/egress.py
"""
Bounded Context:  Platform Infrastructure (shared by all BCs)
Responsibility:   Network egress policy for workflow nodes (SSRF hardening) and
                  the DNS-rebinding-safe HTTP client every node must use.
Owns:             HttpEgressError, EgressTarget, check_egress_target(),
                  check_egress_host(), validate_http_egress_url(),
                  EgressTransport / egress_client(), is_blocked_ip(),
                  host_on_allowlist(), validated_webhook_ips().
Must NOT:         Cache env reads at import time (token/mode rotation).
Dependencies:     stdlib (ipaddress, socket, urllib.parse), httpx (lazy),
                  app.core.config.

Policy (F19 / F-02 — safe by default):

* ``GRAPHYN_HTTP_EGRESS_MODE=restricted`` is the **default**. Every resolved
  address must be globally routable: loopback, RFC1918, CGNAT, link-local
  (incl. ``169.254.169.254``), IPv6 ULA / link-local, multicast, reserved and
  unspecified are denied — unless the target is explicitly listed in
  ``GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW`` (trusted internal services such as a
  local Ollama: ``ollama:11434,172.17.0.1:11434,10.0.0.0/8``).
* Cloud-metadata hosts/addresses (``169.254.0.0/16``, ``fe80::/10``,
  ``fd00:ec2::254``, ``100.100.100.200``, ``metadata.google.internal``) are
  denied in **every** mode and can never be allowlisted.
* ``GRAPHYN_HTTP_EGRESS_ALLOWLIST`` (optional) additionally restricts public
  hosts to the listed domains.
* ``trusted`` is an explicit operator opt-out (private targets allowed;
  metadata still denied).

Resolve-then-connect: :class:`EgressTransport` resolves + validates the host
for **every** request (so each redirect hop is re-checked) and connects to the
validated IP (Host header and TLS SNI/cert verification stay on the original
hostname), so a DNS answer that changes between check and connect cannot
retarget the socket. ``trust_env`` is off (no proxy bypass).

Error messages never embed the full URL (path/query/userinfo may carry
webhook tokens); they use redact_webhook_url_for_api().
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.core.config import (
    http_egress_allowlist,
    http_egress_internal_allowlist,
    http_egress_mode,
)

log = logging.getLogger(__name__)

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORTS = {"http": 80, "https": 443}

# Hostnames commonly used for cloud instance metadata (always blocked).
_METADATA_HOSTS = frozenset({
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
    "instance-data",
    "metadata.azure.com",
})

# Networks that are denied in every mode and can never be allowlisted
# (instance metadata services live here).
_NEVER_ALLOW_NETS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "169.254.0.0/16",
        "fe80::/10",
        "fd00:ec2::254/128",
        "100.100.100.200/32",
    )
)


class HttpEgressError(RuntimeError):
    """Raised when a workflow network destination is denied by egress policy."""


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any address that is not globally routable.

    Uses ``not ip.is_global`` so CGNAT / shared space (100.64.0.0/10, incl.
    Alibaba metadata 100.100.100.200), benchmarking, documentation and other
    special-purpose ranges are denied in addition to private, loopback,
    link-local, ULA, reserved, multicast and unspecified. IPv4-mapped /
    embedded IPv6 forms are checked against their IPv4 address.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is None and ip.sixtofour is not None:
            mapped = ip.sixtofour
        if mapped is None and ip.teredo is not None:
            mapped = ip.teredo[1]
        if mapped is not None and is_blocked_ip(mapped):
            return True
    return bool(
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _unmapped(ip: ipaddress.IPv4Address | ipaddress.IPv6Address):
    if isinstance(ip, ipaddress.IPv6Address):
        for alt in (ip.ipv4_mapped, ip.sixtofour, ip.teredo[1] if ip.teredo else None):
            if alt is not None:
                return alt
    return ip


def is_never_allowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Metadata / link-local addresses: denied in every mode, never allowlistable."""
    for cand in {ip, _unmapped(ip)}:
        for net in _NEVER_ALLOW_NETS:
            if cand.version == net.version and cand in net:
                return True
    return False


def _blocked_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    cand = _unmapped(ip)
    if is_never_allowed_ip(ip):
        return "a link-local / cloud-metadata address"
    if cand.is_loopback:
        return "a loopback address"
    if cand.is_private:
        return "a private (RFC1918 / ULA) address"
    if cand.is_multicast:
        return "a multicast address"
    if cand.is_unspecified:
        return "an unspecified address"
    return "a non-public (reserved / shared) address"


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


def _parse_internal_entry(entry: str) -> tuple[str | None, Any, int | None]:
    """Return ``(hostname, network, port)`` for one INTERNAL_ALLOW entry."""
    raw = entry.strip().lower()
    if "://" in raw:
        parsed = urlparse(raw)
        return (parsed.hostname or None), None, parsed.port
    # CIDR (optionally "cidr" only — no port form for networks)
    if "/" in raw:
        try:
            return None, ipaddress.ip_network(raw, strict=False), None
        except ValueError:
            return None, None, None
    port: int | None = None
    host = raw
    if raw.startswith("["):
        close = raw.find("]")
        host = raw[1:close]
        rest = raw[close + 1 :]
        if rest.startswith(":") and rest[1:].isdigit():
            port = int(rest[1:])
    elif raw.count(":") == 1:
        host, _, p = raw.partition(":")
        if p.isdigit():
            port = int(p)
    try:
        ip = ipaddress.ip_address(host)
        return None, ipaddress.ip_network(ip), port
    except ValueError:
        return host.rstrip("."), None, port


def internal_target_allowed(
    hostname: str,
    port: int | None,
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    entries: list[str] | None = None,
) -> bool:
    """True when ``hostname``/``ip``/``port`` matches GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW."""
    if is_never_allowed_ip(ip):
        return False
    items = entries if entries is not None else http_egress_internal_allowlist()
    host = (hostname or "").lower().rstrip(".")
    for entry in items:
        e_host, e_net, e_port = _parse_internal_entry(entry)
        if e_port is not None and port is not None and e_port != port:
            continue
        if e_host and host and host == e_host:
            return True
        if e_net is not None:
            for cand in {ip, _unmapped(ip)}:
                if cand.version == e_net.version and cand in e_net:
                    return True
    return False


def _resolve_ips(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve *hostname* via getaddrinfo (IPv4 + IPv6 when available)."""
    try:
        return [ipaddress.ip_address(hostname.strip("[]"))]
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


@dataclass
class EgressTarget:
    """A validated destination: connect only to one of ``ips``."""

    scheme: str
    hostname: str
    port: int | None
    ips: list[str] = field(default_factory=list)
    mode: str = "restricted"
    internal: bool = False


def _effective_mode(mode: str | None) -> str:
    effective = (mode or http_egress_mode()).lower()
    if effective not in ("trusted", "restricted"):
        raise HttpEgressError(
            f"HTTP egress: unknown mode {effective!r}; use restricted|trusted."
        )
    return effective


def check_egress_host(
    hostname: str,
    port: int | None,
    *,
    mode: str | None = None,
    purpose: str = "HTTP",
    label: str | None = None,
) -> EgressTarget:
    """Resolve + validate ``hostname:port`` against egress policy.

    Returns the validated addresses (connect to one of them — never re-resolve).
    Raises :class:`HttpEgressError` with a clear, URL-redacted reason.
    """
    effective = _effective_mode(mode)
    shown = label or hostname
    host = (hostname or "").strip()
    if not host:
        raise HttpEgressError(f"{purpose} egress: a hostname is required.")
    host_l = host.lower().rstrip(".").strip("[]")
    if host_l in _METADATA_HOSTS:
        raise HttpEgressError(
            f"{purpose} egress blocked: {shown} is a cloud-metadata host "
            "(always denied, cannot be allowlisted)."
        )
    internal_entries = http_egress_internal_allowlist()
    allowlist = http_egress_allowlist() if effective == "restricted" else []
    ips = _resolve_ips(host_l)
    allowed: list[str] = []
    internal = False
    for ip in ips:
        if is_never_allowed_ip(ip):
            raise HttpEgressError(
                f"{purpose} egress blocked: {shown} resolves to {ip}, "
                f"{_blocked_reason(ip)} (always denied, cannot be allowlisted)."
            )
        if effective == "restricted" and is_blocked_ip(ip):
            if internal_target_allowed(host_l, port, ip, internal_entries):
                internal = True
            else:
                raise HttpEgressError(
                    f"{purpose} egress blocked: {shown} resolves to {ip}, "
                    f"{_blocked_reason(ip)}. Private/internal destinations are denied "
                    "by default (SSRF protection). To allow a trusted internal service, "
                    "add it to GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW (e.g. 'ollama:11434')."
                )
        allowed.append(str(ip))
    if allowlist and not internal and not host_on_allowlist(host_l, allowlist):
        raise HttpEgressError(
            f"{purpose} egress blocked: host {host_l!r} is not on "
            "GRAPHYN_HTTP_EGRESS_ALLOWLIST."
        )
    return EgressTarget(
        scheme="", hostname=host_l, port=port, ips=allowed, mode=effective, internal=internal
    )


def check_egress_target(url: str, *, mode: str | None = None) -> EgressTarget:
    """Validate an http(s) *url*; return the :class:`EgressTarget` to pin to."""
    url = (url or "").strip()
    if not url:
        raise HttpEgressError("HTTP egress: URL is required.")
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise HttpEgressError(
            f"HTTP egress: scheme {scheme!r} is not allowed (use http or https). "
            f"URL={redact_webhook_url_for_api(url)!r}"
        )
    hostname = parsed.hostname
    if not hostname:
        raise HttpEgressError(
            f"HTTP egress: URL must include a hostname. URL={redact_webhook_url_for_api(url)!r}"
        )
    try:
        port = parsed.port or _DEFAULT_PORTS.get(scheme)
    except ValueError as exc:
        raise HttpEgressError(f"HTTP egress: invalid port in URL: {exc}") from exc
    target = check_egress_host(
        hostname, port, mode=mode, purpose="HTTP",
        label=redact_webhook_url_for_api(url).replace("/***", ""),
    )
    target.scheme = scheme
    return target


def validate_http_egress_url(url: str, *, mode: str | None = None) -> None:
    """Validate *url* against the configured HTTP egress policy (raises on deny).

    Prefer :func:`egress_client` for the request itself: it re-validates and
    pins the connection to the validated IP (DNS-rebinding safe).
    """
    check_egress_target(url, mode=mode)


# ── DNS-rebinding-safe HTTP client ────────────────────────────────────────────

def _make_transport_class():
    import httpx

    class EgressTransport(httpx.HTTPTransport):
        """httpx transport that validates + IP-pins every request (each redirect hop)."""

        def __init__(self, *args: Any, mode: str | None = None, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._egress_mode = mode

        def handle_request(self, request: "httpx.Request") -> "httpx.Response":
            target = check_egress_target(str(request.url), mode=self._egress_mode)
            if not target.ips:
                return super().handle_request(request)
            pinned = target.ips[0]
            headers = request.headers.copy()
            # Host header keeps the logical host[:port] (brackets for IPv6).
            headers["Host"] = request.url.netloc.decode("ascii")
            extensions = dict(request.extensions)
            if target.scheme == "https":
                extensions["sni_hostname"] = target.hostname
            pinned_req = httpx.Request(
                request.method,
                request.url.copy_with(host=pinned),
                headers=headers,
                stream=request.stream,
                extensions=extensions,
            )
            return super().handle_request(pinned_req)

    return EgressTransport


_TRANSPORT_CLS = None


def egress_transport(*, mode: str | None = None, **kwargs: Any):
    """Return a new :class:`EgressTransport` instance."""
    global _TRANSPORT_CLS
    if _TRANSPORT_CLS is None:
        _TRANSPORT_CLS = _make_transport_class()
    return _TRANSPORT_CLS(mode=mode, **kwargs)


def egress_client(
    *,
    timeout: float | Any = 30.0,
    follow_redirects: bool = False,
    max_redirects: int = 5,
    mode: str | None = None,
    **kwargs: Any,
):
    """``httpx.Client`` whose every request (and redirect hop) is egress-checked + IP-pinned."""
    import httpx

    return httpx.Client(
        transport=egress_transport(mode=mode),
        timeout=timeout,
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
        trust_env=False,
        **kwargs,
    )


def egress_request(method: str, url: str, **kwargs: Any):
    """One-shot egress-safe request (``httpx.request`` signature subset)."""
    timeout = kwargs.pop("timeout", 30.0)
    follow = kwargs.pop("follow_redirects", False)
    with egress_client(timeout=timeout, follow_redirects=follow) as client:
        resp = client.request(method, url, **kwargs)
        resp.read()
        return resp


from contextlib import contextmanager


@contextmanager
def egress_stream(method: str, url: str, **kwargs: Any):
    """Egress-safe drop-in for ``httpx.stream`` (redirects not followed by default)."""
    timeout = kwargs.pop("timeout", 30.0)
    follow = kwargs.pop("follow_redirects", False)
    with egress_client(timeout=timeout, follow_redirects=follow) as client:
        with client.stream(method, url, **kwargs) as resp:
            yield resp


def egress_post(url: str, **kwargs: Any):
    return egress_request("POST", url, **kwargs)


def egress_get(url: str, **kwargs: Any):
    return egress_request("GET", url, **kwargs)


def validated_webhook_ips(url: str) -> list[str]:
    """Return the public addresses ``url`` resolved to, after webhook SSRF checks.

    The returned list is the exact set just validated. Callers that connect
    must use one of these addresses (IP pin) so a later DNS change cannot
    retarget the socket.
    """
    url = (url or "").strip()
    if not url:
        raise ValueError("Webhook URL is required.")

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"Webhook URL must use http or https scheme, got {scheme!r}. "
            f"URL: {redact_webhook_url_for_api(url)!r}"
        )
    hostname = parsed.hostname
    if not hostname or not parsed.netloc:
        raise ValueError(
            f"Webhook URL must have a valid host. URL: {redact_webhook_url_for_api(url)!r}"
        )

    host_l = hostname.lower().rstrip(".")
    if host_l in _METADATA_HOSTS:
        raise ValueError(
            f"Webhook URL '{redact_webhook_url_for_api(url)}' uses blocked metadata host {hostname!r}."
        )

    try:
        ips = _resolve_ips(hostname)
    except HttpEgressError as exc:
        raise ValueError(str(exc)) from exc

    for ip in ips:
        if is_blocked_ip(ip):
            raise ValueError(
                f"Webhook URL '{redact_webhook_url_for_api(url)}' resolves to a private or loopback address "
                f"({ip}). Webhook targets must be publicly reachable hosts."
            )
    return [str(ip) for ip in ips]


def validate_webhook_target_url(url: str) -> None:
    """Validate an admin-configured webhook URL (always SSRF-hardened).

    Unlike workflow nodes, platform webhooks always block private/loopback/
    link-local/reserved targets regardless of ``GRAPHYN_HTTP_EGRESS_MODE``.

    Raises:
        ValueError: when the URL is denied (wraps :class:`HttpEgressError`).
    """
    validated_webhook_ips(url)


def webhook_url_log_label(url: str) -> str:
    """Return scheme+host for logs (never log path/query — may contain secrets)."""
    parsed = urlparse(url or "")
    if parsed.scheme and parsed.hostname:
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return f"{parsed.scheme}://{host}"
    return "<invalid-url>"


def redact_webhook_url_for_api(url: str) -> str:
    """Redact a webhook URL for API / audit / trace responses.

    Returns ``scheme://host[:port]`` only. Webhook secrets commonly live in the
    path (``/hooks/<token>``) or query string, so path/query/fragment/userinfo
    are never returned — a non-empty path becomes ``/***``. Empty input stays
    empty; unparseable URLs become ``***`` (SEC-P0).
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.hostname:
        return "***"
    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"
    # Never include userinfo / path / query / fragment — path often *is* the secret.
    if parsed.path and parsed.path not in ("", "/"):
        return f"{parsed.scheme}://{host}/***"
    return f"{parsed.scheme}://{host}"

