"""Check semantics: success rule, timing, redirects, timeout, connection errors."""

from __future__ import annotations

import httpx
import pytest

from app import checker


@pytest.fixture(autouse=True)
def _skip_dns_lookup(monkeypatch):
    """These tests exercise HTTP semantics, not the SSRF guard (see test_ssrf.py)."""
    monkeypatch.setattr(checker, "assert_public_url", lambda url: None)


def client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_200_is_success():
    async def handler(request):
        return httpx.Response(200, text="ok")

    async with client_with(handler) as client:
        result = await checker.check_endpoint("https://example.com", client)

    assert result.is_success is True
    assert result.status_code == 200
    assert result.response_time_ms >= 0
    assert result.error_message is None


@pytest.mark.parametrize("status", [201, 204, 301, 399])
async def test_2xx_and_3xx_are_success(status: int):
    async def handler(request):
        return httpx.Response(status)

    async with client_with(handler) as client:
        result = await checker.check_endpoint("https://example.com", client)

    assert result.is_success is True
    assert result.status_code == status


@pytest.mark.parametrize("status", [400, 404, 500, 503])
async def test_4xx_and_5xx_are_failures(status: int):
    async def handler(request):
        return httpx.Response(status)

    async with client_with(handler) as client:
        result = await checker.check_endpoint("https://example.com", client)

    assert result.is_success is False
    assert result.status_code == status
    assert result.error_message == f"HTTP {status}"


async def test_redirect_is_not_followed():
    calls: list[str] = []

    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.com/next"})

    async with client_with(handler) as client:
        result = await checker.check_endpoint("https://example.com", client)

    assert result.is_success is True
    assert result.status_code == 302
    assert calls == ["https://example.com"]


async def test_timeout_is_recorded_as_failure():
    async def handler(request):
        raise httpx.ConnectTimeout("simulated timeout")

    async with client_with(handler) as client:
        result = await checker.check_endpoint("https://example.com", client)

    assert result.is_success is False
    assert result.status_code is None
    assert result.error_message == "timeout"


async def test_connection_error_is_recorded_with_its_type():
    async def handler(request):
        raise httpx.ConnectError("connection refused")

    async with client_with(handler) as client:
        result = await checker.check_endpoint("https://example.com", client)

    assert result.is_success is False
    assert result.status_code is None
    assert result.error_message is not None
    assert result.error_message.startswith("ConnectError:")


async def test_long_error_messages_are_truncated():
    async def handler(request):
        raise httpx.ConnectError("x" * 500)

    async with client_with(handler) as client:
        result = await checker.check_endpoint("https://example.com", client)

    assert result.error_message is not None
    assert len(result.error_message) <= checker.MAX_ERROR_LENGTH


async def test_body_assertion_passes_when_substring_is_present():
    async def handler(request):
        return httpx.Response(200, text='{"status":"healthy","latency":12}')

    async with client_with(handler) as client:
        result = await checker.check_endpoint(
            "https://example.com", client, '"status":"healthy"'
        )

    assert result.is_success is True
    assert result.status_code == 200
    assert result.error_message is None


async def test_body_assertion_fails_when_substring_is_missing():
    async def handler(request):
        return httpx.Response(200, text='{"status":"degraded"}')

    async with client_with(handler) as client:
        result = await checker.check_endpoint("https://example.com", client, "healthy")

    assert result.is_success is False
    # The endpoint answered; only the content assertion failed.
    assert result.status_code == 200
    assert result.error_message == 'body did not contain "healthy"'


async def test_body_assertion_only_scans_the_first_64kb():
    marker = "healthy"
    body = "x" * checker.MAX_BODY_CHARS + marker

    async def handler(request):
        return httpx.Response(200, text=body)

    async with client_with(handler) as client:
        result = await checker.check_endpoint("https://example.com", client, marker)

    assert result.is_success is False
    assert result.error_message == f'body did not contain "{marker}"'


async def test_body_assertion_does_not_mask_a_bad_status():
    async def handler(request):
        return httpx.Response(404, text="healthy")

    async with client_with(handler) as client:
        result = await checker.check_endpoint("https://example.com", client, "healthy")

    assert result.is_success is False
    assert result.status_code == 404
    assert result.error_message == "HTTP 404"
