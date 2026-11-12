"""SSRF guard: only public http(s) destinations may be requested."""

from __future__ import annotations

import httpx
import pytest

from app import checker

BLOCKED = [
    "file:///etc/passwd",
    "ftp://example.com/file",
    "not-a-url",
    "http://",
    "http://127.0.0.1:8000/health",
    "http://localhost/",
    "http://10.1.2.3/",
    "http://192.168.1.10/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://0.0.0.0/",
    "http://example.com:99999/",
]


@pytest.mark.parametrize("url", BLOCKED)
def test_blocked_urls(url: str):
    with pytest.raises(checker.BlockedURLError):
        checker.assert_public_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://1.1.1.1/",
        "http://8.8.8.8:8080/health",
    ],
)
def test_public_ip_literals_are_allowed(url: str):
    # Numeric addresses resolve without a DNS query, so this stays offline.
    checker.assert_public_url(url)


async def test_check_endpoint_blocks_private_target_without_sending_request():
    async def handler(request):
        raise AssertionError("the worker must not contact a private address")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await checker.check_endpoint("http://127.0.0.1/", client)

    assert result.is_success is False
    assert result.status_code is None
    assert result.error_message is not None
    assert result.error_message.startswith("blocked:")
