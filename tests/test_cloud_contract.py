from __future__ import annotations

import httpx
import pytest
import respx

from openserp import AsyncOpenSERP, OpenSERP, RateLimitError, SERPError
from openserp.errors import error_from_response


@pytest.mark.parametrize("format", ["json", "markdown", "text", "ndjson"])
@pytest.mark.parametrize(
    "status,code", [(400, "invalid_request"), (429, "rate_limited"), (503, "engine_unavailable")]
)
@respx.mock
def test_preserves_cloud_errors_for_every_format(format: str, status: int, code: str) -> None:
    route = respx.get("https://api.openserp.org/v1/google/search").mock(
        return_value=httpx.Response(
            status,
            json={
                "error": code,
                "code": status,
                "message": "Request rejected.",
                "retry_after": 60,
            },
            headers={"Retry-After": "60", "X-Request-Id": "req_error"},
        )
    )
    with OpenSERP(api_key="osk_live_test") as client, pytest.raises(SERPError) as caught:
        client.search(engine="google", text="test", format=format)
    err = caught.value
    assert err.status == status
    assert err.code == code
    assert err.request_id == "req_error"
    assert err.retry_after == 60
    assert isinstance(err, RateLimitError) == (status == 429)
    assert route.call_count == 1


@pytest.mark.parametrize(
    "header,body,expected",
    [
        ("45", 60, 45),
        (None, 60, 60),
        ("invalid", 60, 60),
        ("0", 60, 0),
        (None, -1, None),
        (None, True, None),
        (None, "", None),
    ],
)
def test_retry_delay(header: str | None, body: object, expected: float | None) -> None:
    err = error_from_response(
        503, {"error": "engine_unavailable", "retry_after": body}, retry_after=header
    )
    assert err.retry_after == expected


@pytest.mark.parametrize("method,mode", [("any_search", "any"), ("fast_search", "fast")])
@respx.mock
def test_paging_and_compact_metadata(method: str, mode: str) -> None:
    route = respx.get("https://api.openserp.org/v1/mega/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "meta": {"request_id": "req_page", "engine_used": "bing"},
                "results": [{"title": "Page 2", "url": "https://example.com", "engine": "bing"}],
                "pagination": {"page": 2, "has_more": True, "next_start": 20},
            },
            headers={"X-Engine-Used": "bing", "X-Request-Id": "req_page"},
        )
    )
    with OpenSERP(api_key="osk_live_test") as client:
        page = getattr(client, method)(text="test", engines=["google", "bing"], limit=10, start=10)
        assert page.meta.engine_used == "bing"
        assert page.meta.engines_tried is None
        assert page.meta.engines_skipped is None
        assert page.pagination.next_start == 20
        assert client.last_response.engine_used == "bing"
    params = route.calls.last.request.url.params
    assert params["start"] == "10"
    assert params["mode"] == mode
    assert params["engines"] == "google,bing"
    assert route.calls.last.request.headers["authorization"] == "Bearer osk_live_test"


@pytest.mark.parametrize(
    "payload",
    [
        {"engines": {"google": {"status": "operational"}}},
        {"engines": {}},
        {"overall": "degraded"},
    ],
)
@respx.mock
def test_engine_status(payload: dict[str, object]) -> None:
    respx.get("https://api.openserp.org/v1/engines/status").mock(
        return_value=httpx.Response(200, json=payload)
    )
    with OpenSERP(backend="cloud", base_url="https://api.openserp.org/v1") as client:
        status = client.engines_status()
        if "overall" in payload:
            assert status.overall == payload["overall"]
            assert status.engines is None
        else:
            assert status.engines is not None
            assert set(status.engines) == set(payload["engines"])


@respx.mock
@pytest.mark.asyncio
async def test_async_errors_and_status() -> None:
    respx.get("https://api.openserp.org/v1/google/search").mock(
        return_value=httpx.Response(503, json={"error": "engine_unavailable", "retry_after": 60})
    )
    respx.get("https://api.openserp.org/v1/engines/status").mock(
        return_value=httpx.Response(200, json={"engines": {"google": {"status": "operational"}}})
    )
    async with AsyncOpenSERP(api_key="osk_live_test") as client:
        with pytest.raises(SERPError) as caught:
            await client.search(engine="google", text="test", format="markdown")
        assert caught.value.code == "engine_unavailable"
        assert caught.value.retry_after == 60
        assert (await client.engines_status()).engines["google"].status == "operational"
