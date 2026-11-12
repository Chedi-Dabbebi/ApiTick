"""Endpoint checking: URL validation (SSRF guard) and a single HTTP probe.

This module deliberately imports no FastAPI, SQLAlchemy, or scheduler code so
it can be unit-tested in milliseconds with a mocked transport.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from time import perf_counter
from urllib.parse import urlsplit

import httpx

# A check "succeeds" when the endpoint answers with any 2xx or 3xx status.
# This is the single place the rule lives; change it here and nowhere else.
SUCCESS_MIN = 200
SUCCESS_MAX = 399

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MAX_ERROR_LENGTH = 200
# Body assertions only scan the first 64 kB: enough for any JSON/health
# payload, and it keeps a giant response from making every check expensive.
MAX_BODY_CHARS = 64_000

ALLOWED_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True, slots=True)
class CheckResult:
    is_success: bool
    status_code: int | None
    response_time_ms: int
    error_message: str | None = None


class BlockedURLError(ValueError):
    """URL is invalid or resolves somewhere the worker must not request."""


def assert_public_url(url: str) -> None:
    """Reject anything that is not a plain http(s) URL on a public IP.

    Known limitation (documented in the README): DNS is resolved here and then
    again by httpx, so a hostile resolver could in theory rebind between the
    two lookups. Redirects are disabled, which removes the easier variant.
    """
    parsed = urlsplit(url.strip())

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedURLError("only http:// and https:// URLs are supported")

    host = parsed.hostname
    if not host:
        raise BlockedURLError("URL must include a hostname")

    try:
        port = parsed.port
    except ValueError as exc:
        raise BlockedURLError("invalid port in URL") from exc

    if port is not None and not 0 < port < 65_536:
        raise BlockedURLError("port out of range")

    default_port = 443 if parsed.scheme.lower() == "https" else 80

    try:
        resolved = socket.getaddrinfo(host, port or default_port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise BlockedURLError(f"could not resolve host: {host}") from exc

    if not resolved:
        raise BlockedURLError(f"could not resolve host: {host}")

    for info in resolved:
        # IPv6 link-local addresses arrive as "fe80::1%eth0".
        raw_ip = info[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError as exc:
            raise BlockedURLError("host resolved to an unparseable address") from exc

        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped

        if not _is_public_ip(ip):
            raise BlockedURLError("URL resolves to a non-public address")


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_global and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def check_endpoint(
    url: str, client: httpx.AsyncClient, expected_body_contains: str | None = None
) -> CheckResult:
    """Probe one URL. Never raises for network problems — returns a result.

    ``expected_body_contains`` is an optional substring that must appear in the
    response body. It is only evaluated when the status is already successful,
    so a 404 keeps its clearer "HTTP 404" message.
    """
    try:
        assert_public_url(url)
    except BlockedURLError as exc:
        return CheckResult(False, None, 0, _short(f"blocked: {exc}"))

    start = perf_counter()
    try:
        response = await client.get(url, follow_redirects=False)
        elapsed = _elapsed_ms(start)
        ok = SUCCESS_MIN <= response.status_code <= SUCCESS_MAX

        if ok and expected_body_contains:
            body = response.text[:MAX_BODY_CHARS]
            if expected_body_contains not in body:
                return CheckResult(
                    False,
                    response.status_code,
                    elapsed,
                    _short(f'body did not contain "{expected_body_contains}"'),
                )

        return CheckResult(
            is_success=ok,
            status_code=response.status_code,
            response_time_ms=elapsed,
            error_message=None if ok else f"HTTP {response.status_code}",
        )
    except httpx.TimeoutException:
        return CheckResult(False, None, _elapsed_ms(start), "timeout")
    except (httpx.HTTPError, httpx.InvalidURL, OSError) as exc:
        return CheckResult(
            False, None, _elapsed_ms(start), _short(f"{type(exc).__name__}: {exc}")
        )


def _elapsed_ms(start: float) -> int:
    return max(0, int((perf_counter() - start) * 1000))


def _short(message: str) -> str:
    return message if len(message) <= MAX_ERROR_LENGTH else message[: MAX_ERROR_LENGTH - 3] + "..."
